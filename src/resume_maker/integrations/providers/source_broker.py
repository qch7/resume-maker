"""使用请求级回环通道连接只读工具和持有原件的受信任后端"""

import json
import secrets
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

from resume_maker.integrations.providers.base import ProviderError


@contextmanager
def source_broker(access):
    """随机凭据只供本轮 MCP 进程使用，退出时先停止原件读取再关闭连接"""
    if access is None:
        yield None
        return
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        """只接受本机持有随机凭据的有界 JSON 请求"""

        def log_message(self, *args):
            """不记录鉴权、工具参数或原始异常"""

        def setup(self):
            """限制不完整请求占用连接的时间"""
            super().setup()
            self.connection.settimeout(5)

        def do_POST(self):
            """将固定工具调用交给后端校验，响应只包含脱敏结果或通用错误"""
            authorized = secrets.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            )
            if self.path != "/materials" or self.headers.get("Origin") or not authorized:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 64000:
                    raise ValueError("请求过长")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict) or set(request) != {"name", "arguments"}:
                    raise ValueError("请求格式不支持")
                result = {"result": access.call(request["name"], request["arguments"])}
            except (OSError, ValueError, TypeError, AttributeError, ProviderError):
                result = {"error": "读取被拒绝或已取消，请检查授权来源、相对路径及本轮游标。"}
            raw = json.dumps(result, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (OSError, ValueError):
                pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield {"port": server.server_port, "token": token}
    finally:
        access.stopped.set()
        server.shutdown()
        server.server_close()
        thread.join()
