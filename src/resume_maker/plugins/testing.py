"""在独立临时宿主通过公开 HTTP 验收外部插件生命周期"""

import json
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import psutil

from resume_maker.core.process_environment import EnvironmentPolicy, process_environment
from resume_maker.runtime.graph import PluginError


class PluginTestClient:
    """公开测试客户端可供插件作者复用，不需要导入 tests.support"""

    def __init__(self, origin: str, token=""):
        """测试入口固定回环地址，实例令牌由独立宿主首页读取"""
        if not re.fullmatch(r"http://127\.0\.0\.1:\d+", origin):
            raise ValueError("插件验收只接受明确回环地址")
        self.origin, self.token = origin, token
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, method="GET", body=None):
        """请求使用同源实例令牌，HTTP 失败保留明确状态码"""
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("测试接口路径无效")
        request = Request(
            self.origin + path,
            method=method,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"x-resume-token": self.token, "Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.read()
        except HTTPError as exc:
            raise PluginError(f"插件验收接口 {path} 返回 HTTP {exc.code}") from None

    def json(self, path, method="GET", body=None):
        """按公开契约解码 JSON，不访问宿主私有状态"""
        return json.loads(self.request(path, method, body))

    def select(self, selected):
        """单份候选计划完成准备和应用，真实后台执行结束后才算通过"""
        plan = self.json(
            "/api/plugins/plans",
            "POST",
            {
                "generation": self.json("/api/capabilities")["generation"],
                "selected": sorted(selected),
            },
        )
        path = "/api/plugins/plans/" + plan["id"]
        self.json(path + "/prepare", "POST", {"digest": plan["digest"]})
        result = self.json(path + "/apply", "POST", {"digest": plan["digest"]})
        deadline = time.monotonic() + 45
        while result["state"] != "committed" and time.monotonic() < deadline:
            if result["state"] in {"failed", "rolled-back", "recovery-required"}:
                raise PluginError("插件生命周期验收的候选计划未提交")
            time.sleep(0.1)
            try:
                result = self.json(path)
            except (URLError, PluginError):
                self.token = ""
                self.token = re.search(
                    r'name="resume-token" content="([^"]+)"', self.request("/").decode()
                )[1]
        if result["state"] != "committed":
            raise PluginError("插件生命周期验收等待超时")


def test_package(package: Path, enable=()):
    """启动临时资料目录，验证安装、启用、停用及再次启用"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = PluginTestClient(f"http://127.0.0.1:{port}")
    with tempfile.TemporaryDirectory(prefix="plugin-sdk-test-") as temporary:
        root = Path(temporary)
        command = [
            sys.executable,
            "-I",
            "-X",
            "utf8",
            "-m",
            "resume_maker",
            "--data-dir",
            str(root / "data"),
            "--port",
            str(port),
            "--profile",
            "minimal",
            "--no-browser",
            "--no-env-file",
        ]
        with (root / "host.log").open("wb") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=log,
                env=process_environment(EnvironmentPolicy.CANDIDATE),
            )
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise PluginError("临时宿主启动失败，请检查基础依赖及前端构建")
                    try:
                        html = client.request("/").decode()
                        client.token = re.search(r'name="resume-token" content="([^"]+)"', html)[1]
                        if client.json("/api/capabilities")["ready"]:
                            break
                    except (URLError, TimeoutError):
                        time.sleep(0.1)
                else:
                    raise PluginError("临时宿主未在限定时间内就绪")
                inspected = client.json(
                    "/api/plugins/packages/inspect", "POST", {"path": str(package)}
                )
                manifest = inspected["manifest"]
                if manifest.get("data") and manifest["data"].get("schemas"):
                    raise PluginError("有外部表迁移的插件须先用离线资料维护流程验收")
                client.json(
                    "/api/plugins/packages/install",
                    "POST",
                    {
                        "path": str(package),
                        "digest": inspected["digest"],
                        "trusted_modes": inspected["trust_modes"],
                    },
                )
                base = set(client.json("/api/capabilities")["plugins"])
                selected = base | set(enable) | {manifest["id"]}
                client.select(selected)
                if manifest["id"] not in client.json("/api/capabilities")["plugins"]:
                    raise PluginError("插件未进入活动组合")
                client.select(base)
                client.select(selected)
                client.json("/api/shutdown", "POST")
                if process.wait(timeout=20) != 0:
                    raise PluginError("临时宿主未正常关闭")
                return {
                    "valid": True,
                    "plugin": manifest["id"],
                    "checks": ["install", "enable", "disable", "reenable", "shutdown"],
                }
            finally:
                if process.poll() is None:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    for child in reversed(children):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    process.terminate()
                    _, alive = psutil.wait_procs(children, timeout=5)
                    for child in alive:
                        child.kill()
                    process.wait(timeout=10)
