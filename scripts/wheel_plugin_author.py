"""在仓库外通过官方启动器验收仅依赖公开 SDK 的独立插件"""

import json
import os
import re
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import psutil


class Client:
    """只通过本机 HTTP 使用已安装工作台，不访问运行时或测试辅助代码"""

    def __init__(self, port):
        """使用独立回环端口并忽略开发机代理"""
        self.origin = f"http://127.0.0.1:{port}"
        self.token = ""
        self.opener = build_opener(ProxyHandler({}))

    def raw(self, path, method="GET", body=None, expected=200):
        """核对真实 HTTP 状态，失败时只显示接口响应"""
        request = Request(
            self.origin + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"x-resume-token": self.token, "Content-Type": "application/json"},
            method=method,
        )
        try:
            response = self.opener.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            assert response.status == expected, (path, response.status, raw[:500])
            return raw

    def json(self, path, method="GET", body=None):
        """读取公开接口的 JSON 结果"""
        return json.loads(self.raw(path, method, body))

    def select(self, base, names):
        """使用公开变更协议选择自定义实例，明确等待提交完成"""
        current = self.json("/api/capabilities")
        plan = self.json(
            "/api/plugins/plans",
            "POST",
            {
                "generation": current["generation"],
                "selected": sorted(set(base) | set(names)),
                "instances": [
                    {"id": name, "plugin": "community.notes"}
                    for name in ("community.first", "community.second")
                ],
            },
        )
        path = "/api/plugins/plans/" + plan["id"]
        self.json(path + "/prepare", "POST", {"digest": plan["digest"]})
        assert (
            self.json(path + "/apply", "POST", {"digest": plan["digest"]})["state"] == "committed"
        )

    def rpc(self, instance, method, payload=None):
        """每次按公开能力清单固定当前代次"""
        return self.json(
            f"/api/plugins/rpc/{instance}/{method}",
            "POST",
            {
                "generation": self.json("/api/capabilities")["generation"],
                "payload": payload,
            },
        )


@contextmanager
def server(directory, *, initial=False):
    """启动本轮独立官方宿主，优先正常关闭，异常只回收自己创建的进程树"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = Client(port)
    environment = dict(os.environ)
    environment.pop("RESUME_MAKER_FRONTEND_DIR", None)
    command = [
        sys.executable,
        "-I",
        "-X",
        "utf8",
        "-m",
        "resume_maker",
        "--data-dir",
        str(directory),
        "--port",
        str(port),
        "--no-browser",
    ]
    if initial:
        command.extend(["--profile", "minimal"])
    with (directory.parent / "author-host.log").open("ab") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, env=environment)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                assert process.poll() is None, "独立宿主提前退出，见 author-host.log"
                try:
                    html = client.raw("/").decode()
                    client.token = re.search(r'name="resume-token" content="([^"]+)"', html)[1]
                    if client.json("/api/capabilities")["ready"]:
                        break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise AssertionError("独立宿主未在限定时间就绪")
            yield client
            client.json("/api/shutdown", "POST")
            assert process.wait(15) == 0
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
                process.wait(10)


def main():
    """独立构建后验证文档请求、实例资源加载、停用和持久恢复"""
    source = Path(sys.argv[1]).resolve()
    archive = source.parent / "notes.rmp"
    subprocess.run(
        [sys.executable, "-I", str(source / "build.py"), str(archive)], cwd=source, check=True
    )
    directory = source.parent / "author-data"
    with server(directory, initial=True) as client:
        base = client.json("/api/capabilities")["plugins"]
        inspected = client.json("/api/plugins/packages/inspect", "POST", {"path": str(archive)})
        body = json.loads((source / "package-plan.json").read_text(encoding="utf-8"))
        body["generation"] = client.json("/api/capabilities")["generation"]
        body["packages"][0].update(path=str(archive), digest=inspected["digest"])
        planned = client.json("/api/plugins/packages/plans", "POST", body)
        client.json(
            "/api/plugins/plans/" + planned["id"] + "/abort", "POST", {"digest": planned["digest"]}
        )
        client.json("/api/plugins/packages/install", "POST", body["packages"][0])
        client.select(base, ["community.first", "community.second"])
        entries = client.json("/api/capabilities")["client"]
        urls = [item["entry"]["entry"] for item in entries if item["plugin"] == "community.notes"]
        assert len(urls) == 2 and urls[0] == urls[1]
        assert client.raw(urls[0]) == (source / "client/index.js").read_bytes()
        assert client.raw("/shared/react.js")
        for name, text in (("community.first", "合成笔记一"), ("community.second", "合成笔记二")):
            assert client.rpc(name, "save", text) == text
        state = client.json("/api/state")["plugin_notes"]
        assert state["community.first"]["text"] == "合成笔记一"
        client.select(base, ["community.second"])
        assert client.raw(urls[0])
        assert client.rpc("community.second", "read") == "合成笔记二"
        client.select(base, [])
        client.raw(urls[0], expected=404)
        assert "plugin_notes" not in client.json("/api/state")
        client.select(base, ["community.first"])
        assert client.rpc("community.first", "read") == "合成笔记一"
    with server(directory) as client:
        assert client.rpc("community.first", "read") == "合成笔记一"
        client.select(base, ["community.first", "community.second"])
        assert client.rpc("community.second", "read") == "合成笔记二"
    print("仓库外插件作者验收通过：独立构建、文档请求、安装、实例 JS、RPC、停用和恢复有效。")


if __name__ == "__main__":
    main()
