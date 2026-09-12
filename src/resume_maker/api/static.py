"""提供同源前端资源，并把当前实例令牌注入首页。"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from resume_maker.core.config import Config


def mount_frontend(app: FastAPI, config: Config) -> None:
    """挂载构建资源与首页；缺少构建时提供明确的操作提示。"""
    if config.frontend.exists():
        assets = config.frontend / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        """读取已构建首页并注入当前令牌，缺少构建时返回明确提示。"""
        path = config.frontend / "index.html"
        if not path.exists():
            return HTMLResponse(
                "前端尚未构建，请运行 npm --prefix frontend run build。", status_code=503
            )
        return path.read_text(encoding="utf-8").replace("__RESUME_TOKEN__", config.token)
