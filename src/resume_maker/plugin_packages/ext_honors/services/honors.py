"""独立荣誉库：持久条目、证书附件和可取消的串行视觉识别"""

import queue
import re
import shutil
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from resume_maker.core.content import redact
from resume_maker.core.errors import Problem, need
from resume_maker.domain.honors import HonorFields, HonorSave
from resume_maker.domain.models import ProviderSettings
from resume_maker.infrastructure.filesystem import remove_owned_directory
from resume_maker.infrastructure.observability import record, record_event, remember_task
from resume_maker.sdk.imports import ImportContext, ImportSource
from resume_maker.sdk.model import Cancelled
from resume_maker.sdk.observation import internal
from resume_maker.sdk.records import dump, now, uid, unpack


def prepare_certificate(*args):
    """按需加载本机证书解码器"""
    from resume_maker.integrations.certificates import prepare_certificate as prepare

    return prepare(*args)


PREFIX = "honor:"
ACTIVE = {"queued", "running"}


class Honors:
    """集中保存荣誉资料并校验版本，简历按来源标识读取同一份已核对内容"""

    def __init__(self, db, data_dir, provider, *, assets, preserve_sources=None, registry=None):
        """绑定实例资源，构造阶段不启动后台线程"""
        self.db, self.root, self.provider = db, data_dir / "honors", provider
        self.workspaces = data_dir / "workspaces"
        self.lock = threading.RLock()
        self.pending = queue.Queue()
        self.flags = {}
        self.stopped = threading.Event()
        self.worker = None
        self.importers = None
        self.import_registry = registry
        self.assets = assets
        self.execution_queue = None
        self.recognition = None
        self.cleanup_pending = {}
        self.preserve_sources = preserve_sources

    @internal
    def attach_recognition(self, provider, execution_queue, recognition):
        """独占附接识别执行能力，撤销前等待实际任务及清理结束"""
        if self.provider is not None or self.execution_queue is not None:
            raise Problem("荣誉识别能力已附接。", 409)
        self.provider, self.execution_queue, self.recognition = (
            provider,
            execution_queue,
            recognition,
        )

        def detach():
            """保留失败清理所需依赖，成功后恢复手工维护状态"""
            self.stop()
            self.provider, self.execution_queue, self.recognition = None, None, None
            self.stopped.clear()

        return detach

    def start(self):
        """启动单个识别线程，上次退出中断的任务保留原件并允许手动重试"""
        self.stopped.clear()
        self.pending = queue.Queue()
        with self.lock, self.db.transaction() as conn:
            for item in self.list():
                if item["status"] in ACTIVE:
                    item.update(status="failed", error="上次识别被中断，请重新识别或手动填写。")
                    self._write(conn, item)
        if self.execution_queue:
            return
        self.worker = threading.Thread(target=self._work, daemon=True, name="honor-recognition")
        self.worker.start()

    def stop(self):
        """关闭时取消所有在途任务并等待 Provider 回收子进程"""
        with self.lock:
            self.stopped.set()
            for identifier, flag in self.flags.items():
                flag.set()
                self._status(identifier, "cancelled", "应用已关闭，可重新识别。")
        self.pending.put(None)
        if self.execution_queue:
            self.execution_queue.close()
        if self.worker:
            self.worker.join(timeout=10)
            if self.worker.is_alive():
                raise Problem("证书任务尚未结束，保留资源等待取消完成。", 409)
        with self.lock:
            for identifier in list(self.cleanup_pending):
                self._cleanup(identifier)

    def list(self):
        """返回独立荣誉条目，按最近更新排列"""
        with self.db.connect() as conn:
            rows = conn.execute("SELECT value_json FROM settings WHERE key LIKE 'honor:%'")
            return sorted(
                [unpack(row)["value"] for row in rows],
                key=lambda item: item["updated_at"],
                reverse=True,
            )

    def get(self, identifier, conn=None):
        """只读取合法荣誉标识以免附件路径被任意输入控制"""
        try:
            if str(UUID(identifier)) != identifier:
                raise ValueError
        except ValueError as exc:
            raise Problem("荣誉条目不存在。", 404) from exc
        if conn is None:
            with self.db.connect() as connection:
                return self.get(identifier, connection)
        row = unpack(
            conn.execute(
                "SELECT value_json FROM settings WHERE key=?", (PREFIX + identifier,)
            ).fetchone()
        )
        return need(row, "荣誉条目不存在。")["value"]

    def _write(self, conn, item):
        """写入单个条目并递增版本以免多个窗口静默覆盖"""
        item["version"] += 1
        item["updated_at"] = now()
        conn.execute(
            "INSERT OR REPLACE INTO settings VALUES (?,?)", (PREFIX + item["id"], dump(item))
        )

    def _new(self, fields, attachment=None):
        """创建全局荣誉记录"""
        return {
            "id": uid(),
            "fields": fields.model_dump(),
            "attachment": attachment,
            "status": "ready",
            "reviewed": True,
            "recognition": None,
            "error": "",
            "version": 0,
            "created_at": now(),
            "updated_at": now(),
        }

    def save(self, body: HonorSave, identifier=None):
        """保存人工填写和核对后的完整字段，识别中和版本过期时拒绝覆盖"""
        if not body.fields.name:
            raise Problem("请填写荣誉或证书名称。")
        with self.lock, self.db.transaction() as conn:
            item = self.get(identifier, conn) if identifier else self._new(body.fields)
            if item["version"] != body.version:
                raise Problem("此荣誉已更新，请重新打开条目后再保存。", 409)
            if item["status"] in ACTIVE:
                raise Problem("请等待识别完成或先取消识别，再修改信息。", 409)
            item.update(fields=body.fields.model_dump(), reviewed=True, status="ready", error="")
            self._write(conn, item)
            return item

    def upload(self, raw, filename, importer_id=None):
        """完整校验并保存原件后创建待识别条目，失败上传不留下半条记录"""
        filename = Path(filename.replace("\\", "/")).name[:240]
        item = self._new(HonorFields())
        directory = self.root / item["id"]
        directory.mkdir(parents=True)
        try:
            if self.import_registry:
                selected = self.import_registry.select_importer(
                    ImportSource(filename, raw, "certificate"), importer_id
                )
                self.workspaces.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(prefix="certificate-import-", dir=self.workspaces) as stage:
                    result = self.import_registry.run_import(
                        selected, ImportContext(Path(stage), self.stopped)
                    )
                suffix = Path(filename).suffix.lower()
                suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,16}", suffix) else ".bin"
                (directory / ("original" + suffix)).write_bytes(raw)
                for number, page in enumerate(result.pages, 1):
                    (directory / f"page-{number}.png").write_bytes(page)
                metadata = {
                    "pages": len(result.pages),
                    "extension": suffix,
                    "text": result.text,
                    "notices": list(result.notices),
                    "importer": selected.trace,
                }
            else:
                if importer_id:
                    raise Problem("当前荣誉服务未连接导入注册表。", 409)
                metadata = prepare_certificate(raw, filename, directory)
            item.update(
                attachment={"name": filename, "size": len(raw), **metadata},
                reviewed=False,
                status="cancelled",
            )
            resources = self.assets.stage_bundle(
                "ext.honors",
                {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()},
            )
            with self.lock, self.db.transaction() as conn:
                if self.stopped.is_set():
                    raise Problem("应用正在关闭。", 409)
                self.assets.publish_bundle(conn, "ext.honors", f"honors/{item['id']}", resources)
                self._write(conn, item)
            remove_owned_directory(self.root, directory)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return self.recognize(item["id"]) if self.provider else self.get(item["id"])

    def recognize(self, identifier):
        """固化当前识别配置并入队，重复操作或尚未回收的旧任务被拒绝"""
        if self.provider is None:
            raise Problem("荣誉识别插件未启用，请对照原件手工核对。", 409)
        settings = ProviderSettings.model_validate(self.db.setting("provider", {})).for_function(
            "honor_recognition"
        )
        metadata = {
            "handler": "recognize",
            "entities": {"honor_id": identifier},
            "settings": settings.model_dump(),
        }
        with self.lock, self.db.transaction() as conn:
            item = self.get(identifier, conn)
            if self.stopped.is_set() or identifier in self.flags:
                raise Problem("识别任务尚未结束，请稍后重试。", 409)
            if not item["attachment"]:
                raise Problem("此条目没有证书原件。")
            item.update(status="queued", error="")
            self._write(conn, item)
            prepared = (
                self.execution_queue.prepare(conn, identifier, metadata)
                if self.execution_queue
                else None
            )
            self.flags[identifier] = threading.Event()
            if self.db.activity:
                remember_task(self.db.activity, identifier)
        if self.execution_queue:
            try:
                self.execution_queue.submit(
                    identifier,
                    self.flags[identifier],
                    lambda: self._recognize(identifier, settings),
                    metadata,
                    prepared=prepared,
                )
            except Exception:
                with self.lock:
                    self.flags.pop(identifier, None)
                    self._status(identifier, "failed", "任务调度失败，原件已保留，请明确重试。")
                raise
        else:
            self.pending.put((identifier, settings))
        return item

    def cancel(self, identifier):
        """立即标记取消，后台迟到结果不能覆盖人工编辑"""
        with self.lock:
            item = self.get(identifier)
            if identifier in self.flags:
                self.flags[identifier].set()
            if item["status"] in ACTIVE:
                self._status(identifier, "cancelled", "识别已取消，可以手动填写或稍后重试。")
            return self.get(identifier)

    def delete(self, identifier, version):
        """删除库条目并取消识别，关联简历保留删除前最后核对的资料"""
        with self.lock, self.db.transaction() as conn:
            item = self.get(identifier, conn)
            if item["version"] != version:
                raise Problem("此荣誉已更新，请刷新后再删除。", 409)
            if identifier in self.flags:
                self.flags[identifier].set()
            if self.preserve_sources:
                self.preserve_sources(conn)
            self.assets.release_bundle(conn, "ext.honors", f"honors/{identifier}")
            conn.execute("DELETE FROM settings WHERE key=?", (PREFIX + identifier,))
            if identifier not in self.flags:
                shutil.rmtree(self.root / identifier, ignore_errors=True)
        return {"deleted": identifier}

    def file_reference(self, identifier, page=None):
        """核验附件归属和页码后返回资源标识，下载期间由调用方持有租约"""
        item = self.get(identifier)
        attachment = item["attachment"]
        if not attachment:
            raise Problem("此条目没有附件。", 404)
        if page is not None and not 1 <= page <= attachment["pages"]:
            raise Problem("证书页码不存在。", 404)
        name = f"page-{page}.png" if page else "original" + attachment["extension"]
        return {
            "id": self.assets.file_id(f"honors/{identifier}", name),
            "name": attachment["name"],
            "file": name,
        }

    def copy_attachment(self, identifier, page, directory):
        """在租约内复制到本次识别工作目录，名称和类型保留用于隐私预处理"""
        reference = self.file_reference(identifier, page)
        target = directory / reference["file"]
        data = self.assets.read_file(f"honors/{identifier}", reference["file"])
        target.write_bytes(data)
        return target

    def _status(self, identifier, status, error="", result=None):
        """在实例锁内合并任务状态，取消和删除后不发布任何识别结果"""
        record(
            "task",
            status,
            f"证书识别 · {status}",
            {"error": error, "result": result},
            job_id=identifier,
            level="error" if status == "failed" else "info",
        )
        with self.db.transaction() as conn:
            try:
                item = self.get(identifier, conn)
            except Problem:
                return
            if item["status"] not in ACTIVE:
                return
            item.update(status=status, error=error)
            if result:
                item["recognition"] = result.model_dump()
                if not item["reviewed"]:
                    item["fields"] = result.fields.model_dump()
            self._write(conn, item)

    def _work(self):
        """逐个处理证书以保证批量上传不会同时启动大量模型进程"""
        while not self.stopped.is_set():
            task = self.pending.get()
            if task is None:
                return
            identifier, settings = task
            self._recognize(identifier, settings)

    def _recognize(self, identifier, settings):
        """处理单份证书并保留独立任务日志和取消状态"""
        flag = self.flags[identifier]
        workspace = self.workspaces / f"honor-{identifier}-{uid()}"
        try:
            with self.lock:
                if flag.is_set():
                    raise Cancelled("识别已取消。")
                item = self.get(identifier)
                self._status(identifier, "running")
            workspace.mkdir(parents=True)
            result = self.recognition(
                self.provider,
                item,
                settings,
                workspace,
                flag,
                lambda page: self.copy_attachment(identifier, page, workspace),
                self._emit,
            )
            with self.lock:
                if not flag.is_set():
                    self._status(identifier, "review", result=result)
        except Exception as exc:
            with self.lock:
                if not flag.is_set():
                    self._status(
                        identifier, "failed", redact(str(exc))[:1500] or "识别失败，请重试。"
                    )
        finally:
            with self.lock:
                self.cleanup_pending[identifier] = [(self.workspaces, workspace)]
                try:
                    self.get(identifier)
                except Problem:
                    self.cleanup_pending[identifier].append((self.root, self.root / identifier))
                self._cleanup(identifier)

    def _cleanup(self, identifier):
        """附件和临时目录实际回收后才释放识别标识，失败可在停用时重试"""
        pending = self.cleanup_pending[identifier]
        while pending:
            root, directory = pending[0]
            remove_owned_directory(root, directory)
            pending.pop(0)
        self.cleanup_pending.pop(identifier, None)
        self.flags.pop(identifier, None)

    def _emit(self, kind, data):
        """将证书识别进度和工具活动写入统一时间线"""
        record_event(kind, data)
