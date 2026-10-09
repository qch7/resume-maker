"""预构建合成插件包，供安装及升级测试共用"""

import hashlib
import json
from zipfile import ZipFile


def bundle(path, *, worker=False, extra=None, artifacts_extra=None):
    """构造不需要网络和第三方资料的完整预构建插件包"""
    identifier = "community.example"
    manifest = {
        "id": identifier,
        "title": "合成扩展",
        "version": "1.0.0",
        "package": identifier,
        "entrypoints": {
            "host": {"mode": "trusted-host", "entry": "python/plugin.py:activate"},
            "client": {"mode": "trusted-client", "entry": "client/index.js"},
        },
        "provides": {"host": {"example": {"version": "1.0.0"}}},
        "contributes": {"http.routes": ["example/routes"]},
        "permissions": ["workspace.trusted"],
    }
    code = '''from fastapi import APIRouter
from resume_maker.sdk.context import ServiceKey
def activate(context):
    """发布合成扩展的公开服务和命名空间路由"""
    context.provide(ServiceKey("example"), "installed")
    router = APIRouter()
    @router.get("/api/plugins/community.example/hello")
    def hello():
        """返回合成扩展内容"""
        return {"message": "external plugin works"}
    context.contribute("http.routes", "example/routes", tuple(router.routes))
'''
    if worker:
        manifest["entrypoints"] = {"worker": {"mode": "worker", "entry": "python/worker.py"}}
        manifest["requires"] = {
            "host": {"sandbox": ">=1.0.0 <2.0.0", "execution": ">=1.0.0 <2.0.0"}
        }
        manifest["permissions"] = ["execution.trusted"]
        manifest["rpc"] = {
            "double": {"input_schema": {"type": "integer"}, "output_schema": {"type": "integer"}}
        }
        manifest["contributes"] = {}
    files = {
        "LICENSE": b"MIT",
        "python/plugin.py": code.encode(),
        "client/index.js": b"export function activate(context) {}",
        "python/worker.py": (
            b"import json,sys\nr=json.load(sys.stdin)\n"
            b"print(json.dumps({'rpc_version':1,'id':r['id'],'result':r['payload']*2}))\n"
        ),
    }
    if extra:
        manifest.update(extra)
    if artifacts_extra:
        files.update(artifacts_extra)
    files["manifest.json"] = json.dumps(manifest).encode()
    artifacts = {
        name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in files.items()
    }
    files["artifacts.json"] = json.dumps(artifacts).encode()
    with ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return manifest
