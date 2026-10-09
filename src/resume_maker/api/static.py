"""提供同源前端资源并把当前实例令牌注入首页"""

import hashlib
import json
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from resume_maker.core.config import Config
from resume_maker.core.errors import Problem


def mount_frontend(app: FastAPI, config: Config) -> None:
    """挂载构建资源和首页，缺少构建时提供明确的操作提示"""
    if config.frontend.exists():
        assets = config.frontend / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")
        shared = config.frontend / "shared"
        if shared.is_dir():
            app.mount("/shared", StaticFiles(directory=shared), name="shared-sdk")

    @app.get("/plugin-assets/{plugin_id}/{digest}/{resource:path}", include_in_schema=False)
    def plugin_asset(plugin_id: str, digest: str, resource: str):
        """只提供已选插件清单登记的公开客户端产物，不暴露资料和 Python 源码"""
        host = app.state.runtime
        location = host.bootstrap["packages"].get(plugin_id)
        enabled = any(host.definition_id(key) == plugin_id for key in host.selected)
        if not enabled or location is None or location.name != digest:
            raise Problem("插件客户端资源不可用。", 404)
        from resume_maker.runtime.packages import safe_member

        relative = safe_member(resource)
        entry = host.definitions[plugin_id].entrypoints.get("client")
        parent = entry.entry.rpartition("/")[0] if entry else ""
        if entry is None or (parent and not resource.startswith(parent + "/")):
            raise Problem("资源不属于客户端入口。", 404)
        path = location.joinpath(*relative.parts)
        if (
            path.suffix not in {".js", ".mjs", ".css", ".html", ".svg", ".png", ".woff2"}
            or not path.is_file()
            or not path.resolve().is_relative_to(location)
        ):
            raise Problem("客户端资源不存在。", 404)
        from resume_maker.runtime.state import fingerprint

        index = json.loads((location / "artifacts.json").read_text(encoding="utf-8"))
        if fingerprint(index) != digest or resource not in index:
            raise Problem("插件资源清单发生变化。", 409)
        if hashlib.sha256(path.read_bytes()).hexdigest() != index[resource]["sha256"]:
            raise Problem("插件资源摘要发生变化。", 409)
        return FileResponse(path, headers={"Access-Control-Allow-Origin": "*"})

    @app.get("/bundled-plugin-assets/{plugin_id}/{digest}/{resource:path}", include_in_schema=False)
    def bundled_asset(plugin_id: str, digest: str, resource: str):
        """发行包仅公开活动插件索引内的客户端产物，源码和私有文件不可下载"""
        from resume_maker.plugins.client_assets import client_digest, client_directory
        from resume_maker.runtime.packages import safe_member

        host = app.state.runtime
        manifest = host.definitions.get(plugin_id)
        entry = manifest.entrypoints.get("client") if manifest else None
        enabled = any(host.definition_id(key) == plugin_id for key in host.selected)
        if (
            not enabled
            or entry is None
            or not entry.entry.startswith("bundled:")
            or plugin_id in host.bootstrap["packages"]
        ):
            raise Problem("插件客户端资源不可用。", 404)
        location = client_directory(plugin_id).resolve()
        relative = safe_member(resource)
        path = location.joinpath(*relative.parts)
        if (
            path.suffix not in {".js", ".mjs", ".css", ".svg", ".png", ".woff2"}
            or not path.is_file()
            or not path.resolve().is_relative_to(location)
        ):
            raise Problem("客户端资源不存在。", 404)
        if client_digest(plugin_id) != digest:
            raise Problem("插件资源清单发生变化。", 409)
        index = json.loads((location / "artifacts.json").read_text(encoding="utf-8"))
        if resource not in index:
            raise Problem("资源不属于客户端构建。", 404)
        if hashlib.sha256(path.read_bytes()).hexdigest() != index[resource]:
            raise Problem("插件资源摘要发生变化。", 409)
        return FileResponse(path)

    @app.get("/plugin-ui/{plugin_id}/{digest}", include_in_schema=False)
    def isolated_ui(plugin_id: str, digest: str):
        """隔离页面无同源权限，只能通过宿主允许的消息端口调用声明操作"""
        host = app.state.runtime
        manifest = host.definitions.get(plugin_id)
        entry = manifest.entrypoints.get("client") if manifest else None
        if entry is None or entry.mode != "isolated-client":
            raise Problem("插件没有隔离界面。", 404)
        plugin_asset(plugin_id, digest, entry.entry)
        nonce = secrets.token_urlsafe(24)
        prefix = f"/plugin-assets/{plugin_id}/{digest}/"
        source = prefix + quote(entry.entry, safe="/")
        template = Path(__file__).parents[1] / "plugins" / "isolated.html"
        html = (
            template.read_text(encoding="utf-8")
            .replace("__NONCE__", nonce)
            .replace("__ENTRY__", json.dumps(source).replace("<", "\\u003c"))
        )
        origins = [f"http://{name}:{config.port}{prefix}" for name in ("127.0.0.1", "localhost")]
        policy = (
            "default-src 'none'; sandbox allow-scripts; frame-ancestors 'self'; "
            f"script-src 'nonce-{nonce}' {' '.join(origins)}; "
            "style-src 'unsafe-inline'; img-src data:; font-src data:; "
            "connect-src 'none'; form-action 'none'; base-uri 'none'"
        )
        return HTMLResponse(html, headers={"Content-Security-Policy": policy})

    @app.get("/", response_class=HTMLResponse)
    def index():
        """读取已构建首页并注入当前令牌，缺少构建时返回明确提示"""
        path = config.frontend / "index.html"
        if not path.exists():
            return HTMLResponse(
                "前端尚未构建，请运行 npm --prefix frontend run build。", status_code=503
            )
        return path.read_text(encoding="utf-8").replace("__RESUME_TOKEN__", config.token)
