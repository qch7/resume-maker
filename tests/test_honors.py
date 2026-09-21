"""证书上传、识别、人工核对、取消隔离和备份恢复的用户行为回归"""

import threading
import time
from io import BytesIO
from zipfile import ZipFile

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.honors import HonorFields, HonorRecognition
from resume_maker.infrastructure.storage import create_backup, restore_backup


class CertificateProvider:
    """用事件控制识别替身以验证任务协议"""

    def __init__(self):
        """记录模型输入，默认立即返回固定的合成证书信息"""
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = False

    def run_structured(self, **kwargs):
        """检查真实渲染的图像并模拟失败或取消后仍返回的上游"""
        self.calls.append(kwargs)
        self.entered.set()
        assert all(path.read_bytes().startswith(b"\x89PNG") for path in kwargs["images"])
        assert self.release.wait(8)
        if self.fail:
            raise RuntimeError("测试视觉服务暂不可用")
        return HonorRecognition(
            fields=HonorFields(
                name="示例创新竞赛",
                category="竞赛获奖",
                award="一等奖",
                issuer="示例组委会",
                date="2026-06",
                recipient="测试团队",
                certificate_number="DEMO-001",
            ),
            text="示例创新竞赛 一等奖 测试团队 2026年6月",
            warnings=["证书未标注级别，请核对。"],
        )


def certificate_bytes(kind="png", pages=1):
    """生成和用户资料无关的真实图片或多页 PDF，用于解码和预览验证"""
    if kind == "pdf":
        with pymupdf.open() as document:
            for index in range(pages):
                page = document.new_page(width=400, height=280)
                page.insert_text((30, 80), f"Demo Award {index + 1}")
            return document.tobytes()
    buffer = BytesIO()
    Image.new("RGB", (600, 400), "white").save(buffer, kind.upper())
    return buffer.getvalue()


def upload(client, name="certificate.png", raw=None):
    """通过真实二进制 HTTP 入口上传证书"""
    return client.post(
        "/api/honors/upload",
        params={"filename": name},
        content=certificate_bytes() if raw is None else raw,
        headers={"content-type": "application/octet-stream"},
    )


def wait_honor(client, identifier, status="review"):
    """等待可观察的任务状态，超时包含最后一份资料以便定位失败"""
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        item = next(item for item in client.get("/api/honors").json() if item["id"] == identifier)
        if item["status"] == status:
            return item
        time.sleep(0.02)
    pytest.fail(f"荣誉未到达 {status}: {item}")


@pytest.mark.parametrize("kind", ["png", "jpeg", "webp", "pdf"])
def test_upload_recognize_review_and_persist(tmp_path, kind):
    """PDF 和常见图片均生成原件和分页并在核对后独立持久化"""
    provider = CertificateProvider()
    config = Config(data_dir=tmp_path / "data", token="test")
    app = create_app(config, provider)
    app.state.services.db.set_setting(
        "provider",
        {
            "model": "global",
            "reasoning_effort": "high",
            "functions": {"honor_recognition": {"model": "vision-test"}},
        },
    )
    raw = certificate_bytes(kind, pages=2)
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        response = upload(client, f"证书.{kind}", raw)
        assert response.status_code == 201, response.text
        identifier = response.json()["id"]
        item = wait_honor(client, identifier)
        assert item["fields"]["name"] == "示例创新竞赛"
        assert not item["reviewed"]
        assert item["recognition"]["warnings"]
        expected_pages = 2 if kind == "pdf" else 1
        assert len(provider.calls[0]["images"]) == expected_pages
        assert provider.calls[0]["settings"].model == "vision-test"
        assert provider.calls[0]["settings"].reasoning_effort == "high"
        assert client.get(f"/api/honors/{identifier}/original").content == raw
        assert client.get(f"/api/honors/{identifier}/pages/{expected_pages}").content.startswith(
            b"\x89PNG"
        )
        assert client.get(f"/api/honors/{identifier}/pages/0").status_code == 404
        assert client.get(f"/api/honors/{identifier}/pages/{expected_pages + 1}").status_code == 404
        assert (
            client.get(
                f"/api/honors/{identifier}/original", headers={"x-resume-token": "invalid"}
            ).status_code
            == 401
        )
        fields = {**item["fields"], "level": "校级", "name": " 人工确认的奖项 "}
        saved = client.put(
            f"/api/honors/{identifier}", json={"fields": fields, "version": item["version"]}
        )
        assert saved.status_code == 200
        assert saved.json()["reviewed"] and saved.json()["status"] == "ready"
        assert saved.json()["fields"]["name"] == "人工确认的奖项"
        assert (
            client.put(
                f"/api/honors/{identifier}", json={"fields": fields, "version": item["version"]}
            ).status_code
            == 409
        )
        assert client.get("/api/state").json()["resumes"] == []
    with TestClient(create_app(config, provider), headers={"x-resume-token": "test"}) as client:
        restored = client.get("/api/honors").json()[0]
        assert restored["fields"]["name"] == "人工确认的奖项"
        assert client.get(f"/api/honors/{identifier}/original").content == raw
        response = client.post(f"/api/honors/{identifier}/recognize")
        assert response.status_code == 200
        reanalyzed = wait_honor(client, identifier)
        assert reanalyzed["fields"]["name"] == "人工确认的奖项"
        assert reanalyzed["recognition"]["fields"]["name"] == "示例创新竞赛"


def test_failed_recognition_keeps_original_and_allows_manual_save(tmp_path):
    """识别失败不丢文件，人工补充后可以正常使用"""
    provider = CertificateProvider()
    provider.fail = True
    with TestClient(
        create_app(Config(data_dir=tmp_path, token="test"), provider),
        headers={"x-resume-token": "test"},
    ) as client:
        item = upload(client).json()
        failed = wait_honor(client, item["id"], "failed")
        assert "暂不可用" in failed["error"]
        assert client.get(f"/api/honors/{item['id']}/original").status_code == 200
        response = client.put(
            f"/api/honors/{item['id']}",
            json={"fields": {"name": "人工补充证书"}, "version": failed["version"]},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


def test_cancel_and_delete_discard_late_results_and_queue_is_serial(tmp_path):
    """取消后迟到结果不覆盖人工资料，删除排队记录不会被工作线程复活"""
    provider = CertificateProvider()
    provider.release.clear()
    app = create_app(Config(data_dir=tmp_path, token="test"), provider)
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        first = upload(client).json()
        assert provider.entered.wait(4)
        second = upload(client, "second.png").json()
        assert second["status"] == "queued"
        assert len(provider.calls) == 1
        current = wait_honor(client, first["id"], "running")
        assert (
            client.put(
                f"/api/honors/{first['id']}",
                json={"version": current["version"], "fields": {"name": "不允许覆盖"}},
            ).status_code
            == 409
        )
        cancelled = client.post(f"/api/honors/{first['id']}/cancel").json()
        response = client.put(
            f"/api/honors/{first['id']}",
            json={"version": cancelled["version"], "fields": {"name": "取消后的人工资料"}},
        )
        assert response.status_code == 200
        assert (
            client.delete(
                f"/api/honors/{second['id']}", params={"version": second["version"]}
            ).status_code
            == 200
        )
        provider.release.set()
        deadline = time.monotonic() + 4
        while app.state.services.honors.flags and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not app.state.services.honors.flags
        result = client.get("/api/honors").json()
        assert len(result) == 1
        assert result[0]["fields"]["name"] == "取消后的人工资料"
        assert result[0]["recognition"] is None
        assert len(provider.calls) == 1
        assert not (tmp_path / "honors" / second["id"]).exists()


@pytest.mark.parametrize(
    "name,raw,status",
    [
        ("script.svg", b"<svg/>", 415),
        ("broken.pdf", b"not a pdf", 415),
        ("broken.png", b"not an image", 415),
        ("empty.png", b"", 413),
        ("many.pdf", certificate_bytes("pdf", 13), 400),
        ("large.png", b"x" * (20 * 1024 * 1024 + 1), 413),
    ],
    ids=["unsupported", "invalid-pdf", "invalid-image", "empty", "too-many-pages", "too-large"],
)
def test_invalid_upload_leaves_no_record_or_files(tmp_path, name, raw, status):
    """无效格式、空文件、页数超限或体积超限时拒绝导入并清理数据"""
    with TestClient(
        create_app(Config(data_dir=tmp_path, token="test"), CertificateProvider()),
        headers={"x-resume-token": "test"},
    ) as client:
        assert upload(client, name, raw).status_code == status
        assert client.get("/api/honors").json() == []
        assert not list((tmp_path / "honors").glob("*"))


def test_honors_backup_restore_and_delete_preserve_resume_snapshot(tmp_path):
    """荣誉及原件进入现有备份，删除库条目不连带删除简历中采用的文字"""
    directory = tmp_path / "data"
    app = create_app(Config(data_dir=directory, token="test"), CertificateProvider())
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        uploaded = upload(client).json()
        item = wait_honor(client, uploaded["id"])
        created = client.post(
            "/api/resumes",
            json={
                "name": "示例简历",
                "items": [],
                "document": {
                    "sections": [
                        {
                            "id": "honors",
                            "title": "荣誉",
                            "entries": [{"id": f"honor:{item['id']}", "title": "已采用的奖项"}],
                        },
                        {"id": "projects", "title": "项目经历", "kind": "projects"},
                    ]
                },
            },
        )
        assert created.status_code == 200, created.text
        backup = create_backup(app.state.services.db, directory)
        with ZipFile(backup) as archive:
            assert f"honors/{item['id']}/original.png" in archive.namelist()
        target = tmp_path / "restored"
        restore_backup(backup, target)
        incomplete = tmp_path / "incomplete.zip"
        with ZipFile(backup) as source, ZipFile(incomplete, "w") as broken:
            for name in source.namelist():
                if not name.endswith("original.png"):
                    broken.writestr(name, source.read(name))
        with pytest.raises(Problem, match="备份缺少荣誉证书文件"):
            restore_backup(incomplete, tmp_path / "incomplete-restore")
        with TestClient(
            create_app(Config(data_dir=target, token="restored"), CertificateProvider()),
            headers={"x-resume-token": "restored"},
        ) as restored:
            record = restored.get("/api/honors").json()[0]
            assert record["fields"]["name"] == "示例创新竞赛"
            assert restored.get(f"/api/honors/{item['id']}/original").status_code == 200
        assert (
            client.delete(
                f"/api/honors/{item['id']}", params={"version": item["version"] - 1}
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/honors/{item['id']}", params={"version": item["version"]}
            ).status_code
            == 200
        )
        assert client.get(f"/api/honors/{item['id']}/original").status_code == 404
        assert (
            client.get("/api/state").json()["resumes"][0]["document"]["sections"][0]["entries"][0][
                "title"
            ]
            == "已采用的奖项"
        )


def test_restart_marks_unfinished_recognition_as_retryable(tmp_path):
    """上次崩溃遗留的识别状态在启动时变成可重试失败，手工条目保持原样"""
    config = Config(data_dir=tmp_path, token="test")
    app = create_app(config, CertificateProvider())
    with TestClient(app, headers={"x-resume-token": "test"}) as client:
        manual = client.post("/api/honors", json={"fields": {"name": "手动荣誉"}}).json()
        assert client.post("/api/honors", json={"fields": {"name": "   "}}).status_code == 400
        assert client.post(f"/api/honors/{manual['id']}/recognize").status_code == 400
    manual["status"] = "running"
    app.state.services.db.set_setting("honor:" + manual["id"], manual)
    with TestClient(
        create_app(config, CertificateProvider()), headers={"x-resume-token": "test"}
    ) as client:
        restored = client.get("/api/honors").json()[0]
        assert restored["status"] == "failed"
        assert "中断" in restored["error"]
        assert restored["fields"]["name"] == "手动荣誉"
