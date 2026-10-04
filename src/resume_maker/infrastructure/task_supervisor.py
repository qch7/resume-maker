"""持久任务元数据、取消及发布检查的统一协调器"""

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import dump, now, uid, unpack


class TaskSupervisor:
    """任务持有配置快照，重启不自动重放外部操作"""

    def __init__(self, db):
        """创建实例独立的处理器和执行租约表"""
        self.db = db
        self.handlers, self.running = {}, {}
        self.lock = threading.RLock()
        self.executor = None
        self.adapters = {}
        self.owned = {}
        self.condition = threading.Condition(self.lock)
        self.serial = {}
        self.persistence_errors = {}

    def scope(self, owner, generation, providers, version="1.0.0"):
        """业务队列取得固定插件身份和配置快照的调度入口"""
        return OwnedQueue(self, owner, generation, providers, version)

    def attach(self, owner, inspect, cancel):
        """统一读取领域任务的真实状态，兼容队列不复制第二份状态源"""
        with self.lock:
            if owner in self.adapters:
                raise Problem("任务所有者重复登记。", 409)
            self.adapters[owner] = (inspect, cancel)
        return lambda: self.adapters.pop(owner, None)

    def active(self, owners):
        """读取实际活动任务，插件切换据此等待或请求取消"""
        with self.lock:
            adapters = dict(self.adapters)
            running = set(self.running)
            executions = [
                deepcopy(record) for record, _ in self.owned.values() if record["owner"] in owners
            ]
        records = [
            row["value"]
            for row in self.db.all("SELECT value_json FROM settings WHERE key LIKE 'task:%'")
        ]
        result = [
            deepcopy(row) for row in records if row["owner"] in owners and row["id"] in running
        ]
        for owner, (inspect, _) in adapters.items():
            if owner in owners:
                result.extend({**row, "owner": owner} for row in inspect())
        known = {(row["owner"], row["id"]) for row in result}
        result.extend(
            {**row, "id": row["entity_id"], "state": "executing"}
            for row in executions
            if (row["owner"], row["entity_id"]) not in known
        )
        return result

    def prepare(self, conn, queue, identifier, metadata):
        """调度意图同业务输入原子保存，崩溃后明确中断且不自动重放"""
        if self.executor is None:
            raise Problem("系统任务执行器尚未启动。", 409)
        record = {
            "id": uid(),
            "entity_id": identifier,
            "owner": queue.owner,
            "handler": metadata.get("handler", "default"),
            "handler_version": queue.version,
            "generation": queue.generation,
            "providers": deepcopy(queue.providers),
            "request_schema": 1,
            "created_at": now(),
            "finished_at": None,
            "execution_state": "queued",
            "metadata": deepcopy(metadata),
            "retry": "explicit",
            "resumable": False,
        }
        conn.execute(
            "INSERT INTO settings VALUES (?,?)", (f"task-execution:{record['id']}", dump(record))
        )
        return record

    def _finish(self, prefix, record):
        """落盘失败保留可诊断标识，实际结束的线程仍须释放内存租约"""
        try:
            self.db.set_setting(f"{prefix}:{record['id']}", record)
            self.persistence_errors.pop(record["id"], None)
        except Exception as exc:
            self.persistence_errors[record["id"]] = {
                "id": record["id"],
                "owner": record["owner"],
                "error_type": type(exc).__name__,
                "state": "terminal-write-failed",
                "record": deepcopy(record),
                "prefix": prefix,
            }

    def retry_persistence(self):
        """重试结束状态落盘，保留失败项供管理页面诊断"""
        with self.lock:
            for item in list(self.persistence_errors.values()):
                self._finish(item["prefix"], item["record"])
            return self.diagnostics()

    def diagnostics(self):
        """诊断仅包含失败标识，不暴露任务输入和异常正文"""
        with self.lock:
            return [
                {key: item[key] for key in ("id", "owner", "error_type", "state")}
                for item in self.persistence_errors.values()
            ]

    def schedule(self, queue, identifier, flag, work, metadata, prepared=None):
        """统一持有执行句柄，领域结果沿用其原子事务且不复制第二份业务状态"""
        with self.lock:
            if self.executor is None:
                raise Problem("系统任务执行器尚未启动。", 409)
            record = prepared
            if record is None:
                with self.db.transaction() as conn:
                    record = self.prepare(conn, queue, identifier, metadata)
            key = record["id"]
            self.owned[key] = (record, flag)
            serial = self.serial.setdefault(queue.owner, threading.Lock())
            try:
                future = self.executor.submit(self._execute_owned, record, flag, work, serial)
            except BaseException as exc:
                record.update(
                    execution_state="schedule-failed",
                    finished_at=now(),
                    error_type=type(exc).__name__,
                )
                self._finish("task-execution", record)
                self.owned.pop(key, None)
                self.condition.notify_all()
                raise
            return ExecutionHandle(future)

    def _execute_owned(self, record, flag, work, serial):
        """同资源队列串行执行，领域取消后仍持有租约直到真实函数返回"""
        try:
            with serial:
                with self.lock:
                    record["execution_state"] = "running"
                    self.db.set_setting(f"task-execution:{record['id']}", record)
                work()
        except Exception as exc:
            record["error_type"] = type(exc).__name__
        finally:
            with self.condition:
                record.update(
                    execution_state="stopped",
                    finished_at=now(),
                    cancellation_requested=flag.is_set(),
                )
                self._finish("task-execution", record)
                self.owned.pop(record["id"], None)
                self.condition.notify_all()

    def wait_owned(self, owner, timeout=30):
        """取消归属队列并等待实际执行结束，超时保留服务和句柄"""
        with self.condition:
            for record, flag in self.owned.values():
                if record["owner"] == owner:
                    flag.set()
            if not self.condition.wait_for(
                lambda: not any(record["owner"] == owner for record, _ in self.owned.values()),
                timeout,
            ):
                raise Problem("插件任务尚未实际结束，保留执行租约。", 409)

    def cancel_owned(self, owners):
        """取消只发出信号，真实结束仍由活动查询和清理屏障判断"""
        with self.lock:
            for record, flag in self.owned.values():
                if record["owner"] in owners:
                    flag.set()
        for task in self.active(owners):
            adapter = self.adapters.get(task["owner"])
            if adapter:
                adapter[1](task["id"])
            else:
                self.cancel(task["id"])

    def register(self, owner, identifier, handler):
        """以稳定处理器标识登记并返回可撤销入口"""
        key = f"{owner}:{identifier}"
        if key in self.handlers:
            raise Problem("任务处理器重复注册。", 409)
        self.handlers[key] = handler
        return lambda: self.handlers.pop(key, None)

    def start(self):
        """将未结束任务标记中断，只有明确提交才启动新任务"""
        with self.lock:
            if self.executor:
                return
            with self.db.transaction() as conn:
                rows = conn.execute(
                    "SELECT key,value_json FROM settings WHERE key LIKE 'task-execution:%'"
                ).fetchall()
                for raw in rows:
                    item = unpack(raw)
                    record = item["value"]
                    if record["execution_state"] in {"queued", "running"}:
                        record.update(execution_state="interrupted", finished_at=now())
                        conn.execute(
                            "UPDATE settings SET value_json=? WHERE key=?",
                            (dump(record), item["key"]),
                        )
                rows = conn.execute("SELECT key,value_json FROM settings WHERE key LIKE 'task:%'")
                for raw in rows.fetchall():
                    row = unpack(raw)
                    record = row["value"]
                    if record["state"] in {"queued", "running", "cancelling"}:
                        record.update(state="interrupted", finished_at=now())
                        conn.execute(
                            "UPDATE settings SET value_json=? WHERE key=?",
                            (dump(record), row["key"]),
                        )
            self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="plugin-task")

    def submit(self, owner, handler, payload, *, generation, idempotency_key, providers=None):
        """同事务去重并固定代次，执行结果须再次校验取消状态"""
        key = f"{owner}:{handler}"
        with self.lock:
            if key not in self.handlers or self.executor is None:
                raise Problem("任务处理器不可用。", 409)
            with self.db.transaction() as conn:
                existing = conn.execute(
                    "SELECT value_json FROM settings WHERE key LIKE 'task:%' "
                    "AND json_extract(value_json,'$.owner')=? "
                    "AND json_extract(value_json,'$.idempotency_key')=?",
                    (owner, idempotency_key),
                ).fetchone()
                if existing:
                    return unpack(existing)["value"]
                record = {
                    "id": uid(),
                    "owner": owner,
                    "handler": handler,
                    "payload": payload,
                    "generation": generation,
                    "providers": providers or {},
                    "idempotency_key": idempotency_key,
                    "state": "queued",
                    "created_at": now(),
                    "finished_at": None,
                    "result": None,
                }
                conn.execute(
                    "INSERT INTO settings VALUES (?,?)", (f"task:{record['id']}", dump(record))
                )
            cancelled = threading.Event()
            self.running[record["id"]] = cancelled
            try:
                self.executor.submit(self._run, record, self.handlers[key], cancelled)
            except BaseException as exc:
                record.update(state="failed", finished_at=now(), error_type=type(exc).__name__)
                self._finish("task", record)
                self.running.pop(record["id"], None)
                self.condition.notify_all()
                raise
            return deepcopy(record)

    def _run(self, record, handler, cancelled):
        """执行期间持有租约，结束后才发布状态并释放归属"""
        result, succeeded = None, False
        try:
            with self.lock:
                if cancelled.is_set():
                    return
                record["state"] = "running"
                self.db.set_setting(f"task:{record['id']}", record)
            result = handler(record["payload"], cancelled)
            succeeded = True
        except Exception as exc:
            record["error_type"] = type(exc).__name__
        finally:
            with self.condition:
                record.update(
                    state="cancelled"
                    if cancelled.is_set()
                    else "succeeded"
                    if succeeded
                    else "failed",
                    result=result if succeeded and not cancelled.is_set() else None,
                )
                record["finished_at"] = now()
                self._finish("task", record)
                self.running.pop(record["id"], None)
                self.condition.notify_all()

    def cancel(self, identifier):
        """取消请求不伪装为已经终止，实际结束由执行线程确认"""
        with self.lock:
            if event := self.running.get(identifier):
                event.set()
                record = self.db.setting(f"task:{identifier}")
                record["state"] = "cancelling"
                self.db.set_setting(f"task:{identifier}", record)

    def stop(self):
        """等待所有已取消执行真正结束后关闭线程池"""
        with self.condition:
            executor = self.executor
            for event in self.running.values():
                event.set()
            for _, event in self.owned.values():
                event.set()
            if not self.condition.wait_for(lambda: not self.running and not self.owned, 30):
                raise Problem("系统任务仍持有执行租约，关闭尚未完成。", 409)
            self.executor = None
        if executor:
            executor.shutdown(wait=True, cancel_futures=False)
        self.retry_persistence()


class ExecutionHandle:
    """线程兼容的受管句柄，完成条件由统一执行器确认"""

    def __init__(self, future):
        """持有已经入队的唯一执行 future"""
        self.future = future

    def is_alive(self):
        """等待中的任务同样占据执行租约"""
        return not self.future.done()

    def join(self, timeout=None):
        """限时等候，调用方继续通过存活状态判断清理结果"""
        try:
            self.future.result(timeout=timeout)
        except TimeoutError:
            pass


class OwnedQueue:
    """插件任务共享调度器，身份、参数快照和取消归属固定"""

    def __init__(self, supervisor, owner, generation, providers, version):
        """不读取后续活动宿主代次，避免半次任务更换提供方"""
        self.supervisor, self.owner, self.generation = supervisor, owner, generation
        self.providers, self.version = deepcopy(providers), version

    def prepare(self, conn, identifier, metadata):
        """在业务写事务内登记同一次执行意图"""
        return self.supervisor.prepare(conn, self, identifier, metadata)

    def submit(self, identifier, flag, work, metadata, *, prepared=None):
        """领域先提交持久输入，再将实际执行交给系统调度"""
        return self.supervisor.schedule(self, identifier, flag, work, metadata, prepared)

    def close(self):
        """取消信号不代表关闭成功，必须等待执行租约释放"""
        self.supervisor.wait_owned(self.owner)
