"""关联请求、后台任务和适配器活动，统一记录耗时及异常"""

import inspect
import logging
import time
import traceback
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

CURRENT = ContextVar("resume_activity", default=None)


@contextmanager
def activity_scope(log, **fields):
    """为当前线程或异步请求绑定实例日志及关联标识，退出时恢复上层上下文"""
    parent = CURRENT.get()
    values = {**(parent[1] if parent and parent[0] is log else {}), **fields}
    values.setdefault("trace_id", str(uuid4()))
    token = CURRENT.set((log, values))
    try:
        yield values
    finally:
        CURRENT.reset(token)


def record(category, event, title, payload=None, **fields):
    """将当前活动写到所属实例，没有活动上下文时保持原调用行为"""
    current = CURRENT.get()
    if current:
        log, context = current
        log.write(category, event, title, payload, **{**context, **fields})


def record_event(kind, data):
    """统一接收既有任务进度及新增 AI 和工具明细"""
    category = "tool" if kind.startswith("tool") else "ai" if kind.startswith("ai") else "task"
    title = data.get("text") or data.get("tool") or data.get("type") or kind
    record(category, kind, str(title), data, level="error" if kind == "error" else "info")


def protect_secrets(*values):
    """登记当前连接实际使用的凭据，供应商错误意外回显时也会遮盖"""
    current = CURRENT.get()
    if current:
        log = current[0]
        with log.lock:
            log.secrets.update(value for value in values if value)


def remember_task(log, identifier, **fields):
    """在入队前保留请求上下文供工作线程恢复，限制内存中任务索引大小"""
    current = CURRENT.get()
    context = current[1] if current and current[0] is log else {}
    with log.lock:
        if not hasattr(log, "task_contexts"):
            log.task_contexts = OrderedDict()
        log.task_contexts[identifier] = {**context, **fields, "job_id": identifier}
        while len(log.task_contexts) > 2000:
            log.task_contexts.popitem(last=False)


def operation(source, category="service", *, title=None):
    """记录开始、结束和异常，允许按参数生成标题并保留稳定来源及原签名"""

    def decorate(function):
        """将同步业务边界包装成具有独立跨度的可观测操作"""

        @wraps(function)
        def wrapped(*args, **kwargs):
            """在已绑定的日志上下文内执行并保留原异常语义"""
            current = CURRENT.get()
            if not current:
                return function(*args, **kwargs)
            log, parent = current
            span = str(uuid4())
            arguments = dict(inspect.signature(function).bind(*args, **kwargs).arguments)
            arguments.pop("self", None)
            # 进程环境包含凭据且没有业务调试价值，只记录必要启动信息
            arguments.pop("env", None)
            label = title(arguments) if title else source
            with activity_scope(log, span_id=span, parent_span_id=parent.get("span_id", "")):
                started = time.monotonic()
                record(category, "started", label, {"arguments": arguments}, source=source)
                try:
                    result = function(*args, **kwargs)
                except Exception as exc:
                    record(
                        category,
                        "failed",
                        f"{label} · {exc}",
                        {
                            "error": str(exc),
                            "exception": type(exc).__name__,
                            "traceback": traceback.format_exc(),
                        },
                        source=source,
                        level="error",
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                    )
                    raise
                record(
                    category,
                    "completed",
                    label,
                    {"result": result},
                    source=source,
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
                return result

        return wrapped

    return decorate


def instrument_service(service, log, name, *, background=()):
    """集中覆盖服务公开入口及明确的后台执行边界，新增公开方法自动纳入日志"""
    for method_name, method in inspect.getmembers(service, predicate=inspect.ismethod):
        if method_name.startswith("_") and method_name not in background:
            continue
        wrapped = operation(f"{name}.{method_name}")(method)
        setattr(service, method_name, service_entry(wrapped, log, method_name in background))


def service_entry(function, log, background):
    """恢复后台任务的请求关联，并让直接调用服务也有独立日志上下文"""

    @wraps(function)
    def wrapped(*args, **kwargs):
        """从参数提取稳定的项目和会话标识，防止线程间日志串线"""
        arguments = inspect.signature(function).bind(*args, **kwargs).arguments
        fields = {
            key: arguments[key]
            for key in ("job_id", "conversation_id", "project_id")
            if isinstance(arguments.get(key), str)
        }
        if background:
            job = arguments.get("job", {})
            identifier = arguments.get("identifier") or job.get("id", "")
            with log.lock:
                fields = {**getattr(log, "task_contexts", {}).get(identifier, {}), **fields}
            if identifier:
                fields["job_id"] = identifier
            fields.update(
                {key: job[key] for key in ("project_id", "conversation_id") if key in job}
            )
        with activity_scope(log, **fields):
            return function(*args, **kwargs)

    return wrapped


class ActivityHandler(logging.Handler):
    """把当前操作内的 Python 警告和异常转入系统日志"""

    def emit(self, entry):
        """只处理有实例上下文的日志，避免不同应用和框架请求日志互相污染"""
        if CURRENT.get():
            record(
                "system",
                "logging",
                entry.getMessage(),
                {
                    "message": self.format(entry),
                    "logger": entry.name,
                },
                source=entry.name,
                level="error" if entry.levelno >= logging.ERROR else "warning",
            )


def install_logging():
    """进程内只安装一次转接器，实际写入目标由活动上下文决定"""
    logger = logging.getLogger()
    if not any(isinstance(handler, ActivityHandler) for handler in logger.handlers):
        logger.addHandler(ActivityHandler(level=logging.WARNING))
