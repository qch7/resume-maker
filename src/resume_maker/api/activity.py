"""在 ASGI 边界观测请求和响应，不缓存或重放上传及流式正文"""

import json
import time
import traceback
from urllib.parse import parse_qs
from uuid import uuid4

from resume_maker.infrastructure.observability import activity_scope, record

BODY_LIMIT = 32_768


def body_detail(body, size, content_type):
    """JSON 和文字提供有界正文，上传及下载只记录类型和字节数"""
    value = {"content_type": content_type, "bytes": size}
    if "json" in content_type or content_type.startswith("text/"):
        text = body.decode("utf-8", "replace")
        try:
            value["body"] = json.loads(text)
        except ValueError:
            value["body"] = text
        value["truncated"] = size > len(body)
    return value


class ActivityMiddleware:
    """覆盖认证失败和未捕获异常，日志查询自身不产生递归活动"""

    def __init__(self, app, log):
        """保存当前应用的独立日志出口"""
        self.app, self.log = app, log

    async def __call__(self, scope, receive, send):
        """透传协议消息并在响应结束后记录状态、正文摘要和总耗时"""
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or not path.startswith("/api/")
            or path == "/api/activity"
            or path.startswith("/api/activity/")
        ):
            return await self.app(scope, receive, send)
        trace_id, span_id = str(uuid4()), str(uuid4())
        request_body, response_body = bytearray(), bytearray()
        request_size = response_size = 0
        status, response_type = 500, ""
        headers = dict(scope.get("headers", []))
        title = f"{scope['method']} {path}"
        started = time.monotonic()

        async def read():
            """随业务消费请求正文，上传文件不额外驻留内存"""
            nonlocal request_size
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                request_size += len(body)
                request_body.extend(body[: max(0, BODY_LIMIT - len(request_body))])
            return message

        async def write(message):
            """透传响应块并采集有限摘要，保留流式响应及文件下载行为"""
            nonlocal status, response_type, response_size
            if message["type"] == "http.response.start":
                status = message["status"]
                response_type = dict(message.get("headers", [])).get(b"content-type", b"").decode()
                message = {
                    **message,
                    "headers": [*message.get("headers", []), (b"x-request-id", trace_id.encode())],
                }
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                response_size += len(body)
                response_body.extend(body[: max(0, BODY_LIMIT - len(response_body))])
            await send(message)

        with activity_scope(self.log, trace_id=trace_id, span_id=span_id, source="http"):
            record(
                "api",
                "request",
                title,
                {
                    "method": scope["method"],
                    "path": path,
                    "query": parse_qs(scope.get("query_string", b"").decode("utf-8", "replace")),
                    "headers": {
                        key.decode("latin-1"): value.decode("latin-1")
                        for key, value in headers.items()
                    },
                },
            )
            error = None
            try:
                await self.app(scope, read, write)
            except Exception as exc:
                error = {"error": str(exc), "traceback": traceback.format_exc()}
                raise
            finally:
                record(
                    "api",
                    "response",
                    f"{title} · {status}",
                    {
                        "status": status,
                        "request": body_detail(
                            request_body, request_size, headers.get(b"content-type", b"").decode()
                        ),
                        "response": body_detail(response_body, response_size, response_type),
                        "error": error,
                    },
                    level="error"
                    if status >= 500 or error
                    else "warning"
                    if status >= 400
                    else "info",
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
