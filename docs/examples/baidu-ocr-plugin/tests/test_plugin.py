"""独立测试返回契约、计费请求边界和真实宿主中的外部包启停"""

import importlib.util
import json
import random
import sys
import threading
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from zipfile import ZipFile

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.sdk.context import ServiceKey
from resume_maker.sdk.model import Cancelled, ProviderError

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"x-resume-token": "test"}


def load_module(name, path):
    """按外部文件加载插件及标准库构建器，不借用宿主测试辅助代码"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


plugin = load_module("test_baidu_ocr_external", ROOT / "python/plugin.py")
builder = load_module("test_baidu_ocr_build", ROOT / "build.py")
configure = load_module("test_baidu_ocr_configure", ROOT / "configure_credentials.py")


class Vault:
    """合成凭据服务遵循当前公开能力的实际借用方法"""

    def __init__(self, loader):
        """记录无真实密钥的加载器"""
        self.loader = loader

    @contextmanager
    def borrow(self, reference, adapter, purpose):
        """核对插件身份及用途，再读取短生命周期凭据"""
        assert (reference, adapter, purpose) == ("test", plugin.PLUGIN_ID, "ocr")
        with self.loader() as keys:
            yield keys


class Transport:
    """合成传输记录请求，不访问百度或发送个人资料"""

    def __init__(self, *responses):
        """固定响应序列并记录网络尝试次数"""
        self.responses, self.calls = deque(responses), []

    def post(self, url, fields, timeout):
        """模拟接口结果或同步工作结束之后的取消"""
        self.calls.append((url, fields, timeout))
        value = self.responses.popleft()
        if isinstance(value, Exception):
            raise value
        return value() if callable(value) else value


def token():
    """返回仅用于测试的令牌"""
    return {"access_token": "synthetic-token", "expires_in": 3600}


def words(text="Example certificate", confidence=0.98):
    """构造百度含位置版的合成结果"""
    return {
        "words_result": [
            {
                "words": text,
                "location": {"left": 60, "top": 30, "width": 120, "height": 30},
                "probability": {"average": confidence},
            }
        ]
    }


@pytest.fixture
def environment(tmp_path):
    """为每轮测试创建独立配置、图片及合成凭据文件"""
    config = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))["config"]
    credentials = tmp_path / "synthetic-credentials.json"
    configure.write_credentials(credentials, "synthetic-key", "synthetic-secret")
    config.update(
        credentials_file=str(credentials), image_long_side=600, min_request_interval_seconds=0
    )
    path = tmp_path / "image.png"
    Image.new("RGB", (800, 400), "white").save(path)
    return config, credentials, path


def backend(environment, transport):
    """创建实际插件引擎并使用公开凭据契约的替身"""
    config, credentials, _ = environment
    result = plugin.BaiduOCR(
        config, Vault(lambda: plugin.load_credentials(str(credentials))), "test", transport
    )
    result.start()
    return result


def test_image_contract_and_cached_authentication(environment):
    """调用方取得缩放后的归一化位置，连续识别复用鉴权令牌"""
    transport = Transport(token(), words(), words())
    engine = backend(environment, transport)
    for _ in range(2):
        result = engine.read_document(environment[2], threading.Event())
        assert result["text"] == "Example certificate"
        assert result["pages"][0]["width"] == 600
        assert result["pages"][0]["height"] == 300
        assert result["pages"][0]["blocks"][0]["box"] == pytest.approx([0.1, 0.1, 0.3, 0.2])
        assert result["needs_review"] is False
    assert len(transport.calls) == 3
    assert transport.calls[1][1]["probability"] == "true"
    assert transport.calls[1][1]["detect_direction"] == "false"
    assert "accurate?access_token=" in transport.calls[1][0]
    assert "synthetic-secret" not in repr(result)


def test_missing_confidence_requires_review(environment):
    """百度未返回置信度时不能把未知行视为可靠识别"""
    result = words()
    del result["words_result"][0]["probability"]
    engine = backend(environment, Transport(token(), result))
    assert engine.read_document(environment[2], threading.Event())["needs_review"]


def test_general_uses_standard_endpoint_and_its_smaller_limit(environment, tmp_path):
    """标准含位置版使用正确接口，超过其独立上限的请求在上传前拒绝"""
    environment[0]["api"] = "general"
    transport = Transport(token(), words())
    engine = backend(environment, transport)
    engine.read_document(environment[2], threading.Event())
    assert "/general?" in transport.calls[1][0]
    environment[0]["image_long_side"] = 2400
    noise = tmp_path / "noise.png"
    Image.frombytes("RGB", (1800, 1200), random.Random(0).randbytes(1800 * 1200 * 3)).save(noise)
    transport = Transport()
    with pytest.raises(ProviderError, match="8 MB"):
        backend(environment, transport).read_document(noise, threading.Event())
    assert not transport.calls


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"left": float("nan"), "top": 0, "width": 10, "height": 10},
        {"left": 1, "top": 1, "width": -1, "height": 10},
    ],
)
def test_invalid_locations_cannot_reach_layout_recovery(environment, invalid):
    """缺失或错误坐标明确失败，不能发布损坏版面"""
    result = words()
    result["words_result"][0]["location"] = invalid
    engine = backend(environment, Transport(token(), result))
    with pytest.raises(ProviderError):
        engine.read_document(environment[2], threading.Event())


def test_key_rotation_invalidates_token(environment):
    """凭据文件换钥后下一轮识别重新鉴权"""
    transport = Transport(token(), words(), token(), words())
    engine = backend(environment, transport)
    engine.read_document(environment[2], threading.Event())
    environment[1].write_text(json.dumps({"api_key": "new-key", "secret_key": "new-secret"}))
    engine.read_document(environment[2], threading.Event())
    assert len(transport.calls) == 4
    assert transport.calls[2][1]["client_id"] == "new-key"


def test_expired_token_refreshes_only_once(environment):
    """鉴权拒绝可以刷新一次令牌，其他失败不自动重复计费请求"""
    transport = Transport(token(), {"error_code": 110}, token(), words())
    result = backend(environment, transport).read_document(environment[2], threading.Event())
    assert result["text"]
    assert len(transport.calls) == 4


@pytest.mark.parametrize(
    "failure", [{"error_code": 18, "error_msg": "synthetic-secret"}, ProviderError("网络超时")]
)
def test_quota_and_network_failures_are_not_retried(environment, failure):
    """限流和不确定的网络失败由用户决定重试，不回显供应商错误原文"""
    transport = Transport(token(), failure)
    with pytest.raises(ProviderError) as error:
        backend(environment, transport).read_document(environment[2], threading.Event())
    assert "synthetic-secret" not in str(error.value)
    assert len(transport.calls) == 2


def test_cancelled_response_is_discarded(environment):
    """已经发出的请求返回后，取消状态仍阻止采用结果"""
    cancelled = threading.Event()

    def response():
        """模拟网络请求结束时用户已经取消"""
        cancelled.set()
        return words()

    transport = Transport(token(), response)
    engine = backend(environment, transport)
    with pytest.raises(Cancelled):
        engine.read_document(environment[2], cancelled)
    before = len(transport.calls)
    with pytest.raises(Cancelled):
        engine.read_document(environment[2], cancelled)
    assert len(transport.calls) == before


def test_stop_waits_for_actual_request(environment):
    """停用不会在仍有真实识别请求执行时清除引擎资源"""
    started, release, stopped = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def response():
        """模拟尚未结束的网络调用"""
        started.set()
        assert release.wait(5)
        return words()

    engine = backend(environment, Transport(token(), response))

    def read():
        """记录工作线程的取消结果"""
        try:
            engine.read_document(environment[2], threading.Event())
        except Cancelled as error:
            errors.append(error)

    def stop():
        """记录停止屏障的真实完成时间"""
        engine.stop()
        stopped.set()

    reader, stopper = threading.Thread(target=read), threading.Thread(target=stop)
    reader.start()
    assert started.wait(5)
    stopper.start()
    try:
        assert engine.stopping.wait(5)
        assert not stopped.wait(0.05)
    finally:
        release.set()
        reader.join(5)
        stopper.join(5)
    assert stopped.is_set() and errors and not engine.token


def test_native_and_rotated_pdf_do_not_use_paid_requests(environment, tmp_path):
    """可靠文字页本机读取，旋转页面坐标仍相对于可见页面"""
    path = tmp_path / "text.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=200)
        page.insert_text((40, 60), "Example native resume text")
        page.set_rotation(90)
        document.save(path)
    transport = Transport()
    result = backend(environment, transport).read_document(path, threading.Event())
    assert result["pages"][0]["method"] == "pdf-text"
    assert "Example native" in result["text"]
    assert result["pages"][0]["blocks"][0]["box"][0] > 0.5
    assert not transport.calls


def test_scanned_pdf_reads_all_pages(environment, tmp_path):
    """两页扫描 PDF 分别调用接口，不静默只识别第一页"""
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as document:
        for _ in range(2):
            document.new_page(width=200, height=100)
        document.save(path)
    transport = Transport(token(), words("Page one"), words("Page two"))
    result = backend(environment, transport).read_document(path, threading.Event())
    assert result["text"] == "Page one\n\nPage two"
    assert len(result["pages"]) == 2 and len(transport.calls) == 3


def test_hidden_pdf_text_is_not_trusted(environment, tmp_path):
    """隐藏文字层不能替代可见像素识别"""
    path = tmp_path / "hidden.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 60), "Hidden incorrect text", render_mode=3)
        document.save(path)
    transport = Transport(token(), words("Visible page"))
    result = backend(environment, transport).read_document(path, threading.Event())
    assert result["text"] == "Visible page"
    assert len(transport.calls) == 2


def test_page_and_text_limits_stop_further_requests(environment, tmp_path):
    """页数和累计文字超限不会继续向百度提交后续页面"""
    path = tmp_path / "many.pdf"
    with pymupdf.open() as document:
        for _ in range(13):
            document.new_page()
        document.save(path)
    transport = Transport()
    with pytest.raises(ProviderError, match="1–12"):
        backend(environment, transport).read_document(path, threading.Event())
    assert not transport.calls
    with pymupdf.open() as document:
        document.new_page()
        document.new_page()
        document.save(tmp_path / "large-text.pdf")
    transport = Transport(token(), words("x" * 100_001))
    with pytest.raises(ProviderError, match="10 万"):
        backend(environment, transport).read_document(
            tmp_path / "large-text.pdf", threading.Event()
        )
    assert len(transport.calls) == 2


def test_credentials_are_external_and_not_overwritten(environment):
    """交互助手拒绝覆盖已有凭据，插件错误不输出文件内容"""
    with pytest.raises(FileExistsError):
        configure.write_credentials(environment[1], "replacement", "replacement")
    assert "synthetic-key" in environment[1].read_text()
    environment[1].write_text("synthetic-secret")
    with pytest.raises(ProviderError) as error:
        backend(environment, Transport()).read_document(environment[2], threading.Event())
    assert "synthetic-secret" not in str(error.value)


def change_selection(client, selected, configs=None):
    """通过真实 HTTP 预览及应用组合，测试目录没有浏览器草稿屏障"""
    capabilities = client.get("/api/capabilities", headers=HEADERS).json()
    response = client.post(
        "/api/plugins/plans",
        headers=HEADERS,
        json={
            "selected": sorted(selected),
            "generation": capabilities["generation"],
            "configs": configs,
        },
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    path = "/api/plugins/plans/" + plan["id"]
    assert (
        client.post(path + "/prepare", headers=HEADERS, json={"digest": plan["digest"]}).status_code
        == 200
    )
    response = client.post(path + "/apply", headers=HEADERS, json={"digest": plan["digest"]})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "committed"


def test_real_package_install_switch_restore_and_assets(tmp_path):
    """独立包实际安装替换 RapidOCR，停用后旧引擎不可用，重启保留选择"""
    package = builder.build(tmp_path / "baidu.rmp")
    assert package.read_bytes() == builder.build(tmp_path / "repeat.rmp").read_bytes()
    with ZipFile(package) as archive:
        assert set(archive.namelist()) == set(builder.RELEASE_FILES) | {"artifacts.json"}
        assert not any("credentials.json" in name for name in archive.namelist())
    config = Config(data_dir=tmp_path / "host-data", token="test", profile="minimal")
    app = create_app(config)
    with TestClient(app) as client:
        checked = client.post(
            "/api/plugins/packages/inspect", headers=HEADERS, json={"path": str(package)}
        )
        assert checked.status_code == 200, checked.text
        inspection = checked.json()
        assert inspection["manifest"]["id"] == plugin.PLUGIN_ID
        installed = client.post(
            "/api/plugins/packages/install",
            headers=HEADERS,
            json={
                "path": str(package),
                "digest": inspection["digest"],
                "trusted_modes": inspection["trust_modes"],
            },
        )
        assert installed.status_code == 200, installed.text
        selected = set(app.state.runtime.selected)
        change_selection(client, selected | {"provider.rapidocr", "ext.ocr"})
        # 同时发布唯一能力必须在预览阶段拒绝，绑定选择不能覆盖基数约束
        rejected = client.post(
            "/api/plugins/plans",
            headers=HEADERS,
            json={
                "selected": sorted(app.state.runtime.selected | {plugin.PLUGIN_ID}),
                "generation": app.state.runtime.generation,
            },
        )
        assert rejected.status_code == 409 and "ocr.backend" in rejected.text
        selected |= {plugin.PLUGIN_ID, "ext.ocr"}
        change_selection(client, selected)
        generation = app.state.runtime.generation
        status = client.post(
            "/api/plugins/rpc/" + plugin.PLUGIN_ID + "/status",
            headers=HEADERS,
            json={"generation": generation, "payload": None},
        )
        assert status.status_code == 200 and not status.json()["configured"]
        original_backend = app.state.runtime.require(ServiceKey("ocr"))
        asset = (
            "/plugin-assets/" + plugin.PLUGIN_ID + "/" + inspection["digest"] + "/client/index.js"
        )
        assert client.get(asset, headers=HEADERS).status_code == 200
        assert app.state.runtime.resolution.providers["ocr.backend"] == plugin.PLUGIN_ID
        change_selection(client, selected - {plugin.PLUGIN_ID, "ext.ocr"})
        with pytest.raises(Cancelled):
            original_backend(tmp_path / "unused.png", threading.Event())
        assert client.get(asset, headers=HEADERS).status_code == 404
        change_selection(client, selected)
    # 新进程式重建实际重新读取安装记录和所选组合，不使用真实服务鉴权
    restored = create_app(Config(data_dir=config.data_dir, token="test"))
    with TestClient(restored) as client:
        assert restored.state.runtime.resolution.providers["ocr.backend"] == plugin.PLUGIN_ID
        assert client.get(asset, headers=HEADERS).status_code == 200


def test_configured_package_uses_real_credentials_capability(tmp_path, monkeypatch):
    """已配置外部包通过真实凭据服务及统一 OCR 入口完成识别，健康检查失败保留原实例"""
    package = builder.build(tmp_path / "baidu.rmp")
    credential_file, image = tmp_path / "keys.json", tmp_path / "page.png"
    configure.write_credentials(credential_file, "synthetic-key", "synthetic-secret")
    Image.new("RGB", (600, 300), "white").save(image)
    app = create_app(Config(data_dir=tmp_path / "configured-host", token="test", profile="minimal"))
    with TestClient(app) as client:
        inspection = client.post(
            "/api/plugins/packages/inspect", headers=HEADERS, json={"path": str(package)}
        ).json()
        response = client.post(
            "/api/plugins/packages/install",
            headers=HEADERS,
            json={
                "path": str(package),
                "digest": inspection["digest"],
                "trusted_modes": inspection["trust_modes"],
            },
        )
        assert response.status_code == 200, response.text
        selected = app.state.runtime.selected | {plugin.PLUGIN_ID, "ext.ocr"}
        settings = {**inspection["manifest"]["config"], "credentials_file": str(credential_file)}
        change_selection(client, selected, {plugin.PLUGIN_ID: settings})
        reader = app.state.runtime.require(ServiceKey("ocr"))
        transport = Transport(token(), words())
        monkeypatch.setattr(reader.__self__, "transport", transport)
        connected = client.post(
            "/api/plugins/rpc/" + plugin.PLUGIN_ID + "/connect",
            headers=HEADERS,
            json={"generation": app.state.runtime.generation, "payload": None},
        )
        assert connected.status_code == 200 and connected.json()["connected"]
        assert len(transport.calls) == 1
        assert reader(image, threading.Event())["text"] == "Example certificate"
        assert len(transport.calls) == 2
        invalid = {**settings, "credentials_file": str(tmp_path / "missing.json")}
        prepared = client.post(
            "/api/plugins/plans",
            headers=HEADERS,
            json={
                "selected": sorted(selected),
                "generation": app.state.runtime.generation,
                "configs": {plugin.PLUGIN_ID: invalid},
            },
        )
        assert prepared.status_code == 200, prepared.text
        plan = prepared.json()
        path = "/api/plugins/plans/" + plan["id"]
        assert (
            client.post(
                path + "/prepare", headers=HEADERS, json={"digest": plan["digest"]}
            ).status_code
            == 200
        )
        failed = client.post(path + "/apply", headers=HEADERS, json={"digest": plan["digest"]})
        assert failed.status_code == 409 and "恢复" in failed.text
        assert app.state.runtime.configs[plugin.PLUGIN_ID]["credentials_file"] == str(
            credential_file
        )
        status = client.post(
            "/api/plugins/rpc/" + plugin.PLUGIN_ID + "/status",
            headers=HEADERS,
            json={"generation": app.state.runtime.generation, "payload": None},
        )
        assert status.status_code == 200 and status.json()["configured"]


def test_http_form_response_limits_and_redirect_rejection():
    """通过本机合成 HTTP 服务校验实际表单发送及错误边界"""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        """合成端点仅返回固定数据，不连接百度"""

        def do_POST(self):
            """记录实际网络正文并模拟正常、错误及重定向响应"""
            fields = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode("ascii"))
            calls.append((self.path, fields, self.headers["Content-Type"]))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/unexpected")
                self.end_headers()
                return
            if self.path == "/invalid":
                data, status = b"not-json", 502
            elif self.path == "/quota":
                data, status = json.dumps({"error_code": 18}).encode(), 429
            elif self.path == "/huge":
                data, status = b"x" * (plugin.MAX_RESPONSE_BYTES + 1), 200
            else:
                data, status = json.dumps(words()).encode(), 200
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            """测试不输出请求正文或额外服务器日志"""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = "http://127.0.0.1:" + str(server.server_port)
    transport = plugin.Transport()
    try:
        assert transport.post(base + "/ok", {"image": "a+/=", "text": "合成"}, 2) == words()
        assert calls[0][1] == {"image": ["a+/="], "text": ["合成"]}
        assert calls[0][2] == "application/x-www-form-urlencoded"
        assert transport.post(base + "/quota", {}, 2) == {"error_code": 18}
        with pytest.raises(ProviderError, match="HTTP 502"):
            transport.post(base + "/invalid", {}, 2)
        with pytest.raises(ProviderError, match="重定向"):
            transport.post(base + "/redirect", {"client_secret": "synthetic-secret"}, 2)
        assert not any(path == "/unexpected" for path, *_ in calls)
        with pytest.raises(ProviderError, match="上限"):
            transport.post(base + "/huge", {}, 2)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)


def test_only_public_sdk_imports():
    """生产入口只使用 SDK，第三方插件不导入系统或其他插件私有实现"""
    import ast

    tree = ast.parse((ROOT / "python/plugin.py").read_text(encoding="utf-8"))
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert all(
        name.startswith("resume_maker.sdk.")
        for name in modules
        if name and name.startswith("resume_maker")
    )
