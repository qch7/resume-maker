"""本机访问校验、安全响应头与业务异常的 HTTP 映射。"""

import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.integrations.providers.base import ProviderError


def configure_middleware(app: FastAPI, config: Config) -> None:
    """安装本机 Host/Origin/令牌检查，并统一返回可展示的错误消息。"""
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def local_auth(request: Request, call_next):
        """核验本机文件接口的来源和实例令牌，并设置缓存及嵌入防护响应头。"""
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            origin = request.headers.get("origin")
            allowed = {f"http://127.0.0.1:{config.port}", f"http://localhost:{config.port}"}
            if origin and origin not in allowed:
                return JSONResponse({"detail": "不允许跨站访问本机文件接口。"}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-resume-token", ""), config.token):
                return JSONResponse({"detail": "会话已失效，请刷新页面。"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Problem)
    async def problem_handler(_request, exc):
        """把业务异常转换为前端统一识别的 detail 错误响应。"""
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(ValidationError)
    async def validation_handler(_request, exc):
        """将业务模型验证错误转换为 422 响应，避免当作服务器故障。"""
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def missing_handler(_request, _exc):
        """将缺失文件或目录转换为可操作的路径检查提示。"""
        return JSONResponse({"detail": "文件或目录不存在，请检查路径。"}, status_code=404)

    @app.exception_handler(ValueError)
    async def value_handler(_request, exc):
        """将参数或内容值错误转换为 400 响应。"""
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ProviderError)
    async def provider_error_handler(_request, exc):
        """将上游 Provider 故障转换为 502 响应并保留可展示的原因。"""
        return JSONResponse({"detail": str(exc)}, status_code=502)
