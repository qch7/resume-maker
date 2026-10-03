"""招聘收藏夹的文件交换、并发保护和本机持久化"""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.services.recruitment import Recruitment

HEADERS = {"x-resume-token": "test"}


def sample():
    """构造带中文备注和多个网址的小厂收藏，验证用户自定义字段可往返"""
    return {
        "format": "resume-maker.recruitment-bookmarks",
        "schema_version": 1,
        "domains": [{"id": "custom", "name": "自定义领域"}],
        "categories": [{"id": "small", "name": "小厂"}],
        "bookmarks": [
            {
                "id": "custom-company",
                "name": "合成公司",
                "domain_id": "custom",
                "category": "small",
                "description": "合成业务",
                "tags": ["研发", "实习"],
                "notes": "个人备注\n第二行",
                "favorite": True,
                "links": [
                    {"label": "校招", "url": "https://example.com/campus?year=2027#jobs"},
                    {"label": "官网", "url": "https://example.org/"},
                ],
            }
        ],
    }


def import_body(data, revision=0, policy="keep"):
    """生成导入请求，文件内的格式版本不依赖本机保存版本"""
    return {"revision": revision, "policy": policy, "content": json.dumps(data, ensure_ascii=False)}


def test_preview_import_export_restart_and_backup_preserve_custom_data(tmp_path):
    """预览不写入，保存后的顺序、标签和备注在导出重导及备份恢复后完整保留"""
    config = Config(data_dir=tmp_path / "first", token="test")
    app = create_app(config)
    with TestClient(app) as client:
        initial = client.get("/api/recruitment", headers=HEADERS).json()
        assert initial["data"]["bookmarks"] == []
        assert initial["data"]["domains"] == []
        assert initial["data"]["categories"] == []
        body = import_body(sample())
        preview = client.post("/api/recruitment/import/preview", headers=HEADERS, json=body)
        assert preview.status_code == 200
        assert preview.json()["added"] == 1
        assert client.get("/api/recruitment", headers=HEADERS).json() == initial
        imported = client.post("/api/recruitment/import", headers=HEADERS, json=body)
        assert imported.status_code == 200
        saved = imported.json()["snapshot"]
        exported = client.get("/api/recruitment/export", headers=HEADERS)
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        assert exported.json() == saved["data"]
        repeated = client.post(
            "/api/recruitment/import",
            headers=HEADERS,
            json=import_body(exported.json(), saved["revision"]),
        ).json()
        assert repeated["summary"]["skipped"] == 1
        assert repeated["snapshot"] == saved
    with TestClient(create_app(config)) as client:
        assert client.get("/api/recruitment", headers=HEADERS).json() == saved
    archive = create_backup(app.state.services.db, config.data_dir)
    destination = tmp_path / "restored"
    restore_backup(archive, destination)
    assert Recruitment(Database(destination / "resume.db")).get() == saved
    with TestClient(create_app(Config(data_dir=tmp_path / "second", token="test"))) as client:
        imported = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(exported.json())
        ).json()
        assert imported["snapshot"]["data"] == saved["data"]


def test_import_keep_update_and_stale_preview_are_atomic(tmp_path):
    """跳过重复保护本机备注，显式更新替换同 ID，过期预览不能覆盖其他窗口"""
    with TestClient(create_app(Config(data_dir=tmp_path, token="test"))) as client:
        data = sample()
        first = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(data)
        ).json()["snapshot"]
        data["bookmarks"][0]["notes"] = "文件中的新备注"
        keep = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(data, 1)
        ).json()
        assert keep["snapshot"] == first
        preview = client.post(
            "/api/recruitment/import/preview", headers=HEADERS, json=import_body(data, 1, "update")
        ).json()
        assert preview["updated"] == 1
        local = deepcopy(first)
        local["data"]["bookmarks"][0]["name"] = "本机改名"
        assert client.put("/api/recruitment", headers=HEADERS, json=local).status_code == 200
        stale = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(data, 1, "update")
        )
        assert stale.status_code == 409
        assert (
            client.get("/api/recruitment", headers=HEADERS).json()["data"]["bookmarks"][0]["name"]
            == "本机改名"
        )
        updated = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(data, 2, "update")
        ).json()
        assert updated["summary"]["updated"] == 1
        assert updated["snapshot"]["data"]["bookmarks"][0]["notes"] == "文件中的新备注"


@pytest.mark.parametrize(
    "case",
    [
        "format",
        "version",
        "duplicate",
        "domain",
        "category",
        "duplicate-category",
        "unknown",
        "url",
        "credential",
        "blank",
        "json",
    ],
)
def test_invalid_imports_never_change_existing_data(tmp_path, case):
    """错误文件整体拒绝，包含有效和无效记录时也不留下部分数据"""
    with TestClient(create_app(Config(data_dir=tmp_path, token="test"))) as client:
        body = sample()
        current = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(body)
        ).json()["snapshot"]
        data = deepcopy(body)
        data["bookmarks"].append({**deepcopy(data["bookmarks"][0]), "id": "new"})
        if case == "format":
            data["format"] = "other-format"
        elif case == "version":
            data["schema_version"] = 2
        elif case == "duplicate":
            data["bookmarks"][1]["id"] = "custom-company"
        elif case == "domain":
            data["bookmarks"][1]["domain_id"] = "missing"
        elif case == "category":
            data["bookmarks"][1]["category"] = "missing"
        elif case == "duplicate-category":
            data["categories"].append({"id": "another-id", "name": "小厂"})
        elif case == "unknown":
            data["unexpected"] = True
        elif case == "url":
            data["bookmarks"][1]["links"][0]["url"] = "javascript:alert(1)"
        elif case == "credential":
            data["bookmarks"][1]["links"][0]["url"] = "https://name:secret@example.org"
        elif case == "blank":
            data["bookmarks"][1]["name"] = "  "
        payload = import_body(data, 1)
        if case == "json":
            payload["content"] = "{invalid json"
        for path in ["/api/recruitment/import/preview", "/api/recruitment/import"]:
            response = client.post(path, headers=HEADERS, json=payload)
            assert response.status_code == 422, response.text
            assert client.get("/api/recruitment", headers=HEADERS).json() == current


def test_same_name_domains_merge_and_edit_delete_preserve_references(tmp_path):
    """同名领域复用本机标识，删除后导出仍符合格式，多窗口旧保存被拒绝"""
    with TestClient(create_app(Config(data_dir=tmp_path, token="test"))) as client:
        initial = client.get("/api/recruitment", headers=HEADERS).json()
        initial["data"]["domains"] = [{"id": "internet", "name": "互联网"}]
        initial["data"]["categories"] = [{"id": "local-small", "name": "小厂"}]
        current = client.put("/api/recruitment", headers=HEADERS, json=initial).json()
        data = sample()
        data["domains"][0]["name"] = "互联网"
        saved = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(data, current["revision"])
        ).json()["snapshot"]
        assert len(saved["data"]["domains"]) == 1
        assert saved["data"]["bookmarks"][0]["domain_id"] == "internet"
        assert len(saved["data"]["categories"]) == 1
        assert saved["data"]["bookmarks"][0]["category"] == "local-small"
        body = deepcopy(saved)
        body["data"]["domains"].append({"id": "new-domain", "name": "新领域"})
        body["data"]["bookmarks"][0]["domain_id"] = "new-domain"
        body["data"]["domains"].pop(0)
        changed = client.put("/api/recruitment", headers=HEADERS, json=body).json()
        assert changed["data"]["domains"][0]["id"] == "new-domain"
        assert client.put("/api/recruitment", headers=HEADERS, json=saved).status_code == 409
        changed["data"]["bookmarks"] = []
        assert client.put("/api/recruitment", headers=HEADERS, json=changed).status_code == 200
        assert client.get("/api/recruitment/export", headers=HEADERS).json()["bookmarks"] == []


def test_recruitment_routes_are_authenticated_without_bundled_lists(tmp_path):
    """收藏接口遵守本机访问边界，不依赖本地企业清单或提供下载入口"""
    with TestClient(create_app(Config(data_dir=tmp_path, token="test"))) as client:
        for name in ["internet", "technology"]:
            assert (
                client.get(f"/api/recruitment/examples/{name}", headers=HEADERS).status_code == 404
            )
        assert client.get("/api/recruitment/export").status_code == 401
        assert client.get("/api/recruitment").status_code == 401
        assert client.post("/api/recruitment/import", json=import_body(sample())).status_code == 401


def test_empty_collection_custom_categories_and_ungrouped_bookmarks(tmp_path):
    """初始无预置分组，导入自定义分类后可改名或移除，未分组网址仍可保存"""
    with TestClient(create_app(Config(data_dir=tmp_path, token="test"))) as client:
        data = sample()
        data["categories"] = [{"id": "dream", "name": "优先投递"}]
        data["bookmarks"][0]["category"] = "dream"
        data["bookmarks"][0]["domain_id"] = ""
        data["domains"] = []
        preview = client.post(
            "/api/recruitment/import/preview", headers=HEADERS, json=import_body(data)
        ).json()
        assert preview["categories_added"] == 1
        assert client.get("/api/recruitment", headers=HEADERS).json()["data"]["categories"] == []
        saved = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(data)
        ).json()["snapshot"]
        assert saved["data"]["categories"] == data["categories"]
        saved["data"]["categories"][0]["name"] = "本机改名"
        saved = client.put("/api/recruitment", headers=HEADERS, json=saved).json()
        repeated = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(data, saved["revision"])
        ).json()["snapshot"]
        assert repeated == saved
        saved["data"]["categories"] = []
        saved["data"]["bookmarks"][0]["category"] = ""
        assert client.put("/api/recruitment", headers=HEADERS, json=saved).status_code == 200
        exported = client.get("/api/recruitment/export", headers=HEADERS).json()
        assert exported["domains"] == exported["categories"] == []
        assert len(exported["bookmarks"]) == 1


def test_import_preferences_persist_and_do_not_enter_exchange_files(tmp_path):
    """独立设置重启及备份后保留，导入采用读取的规则且网址文件不含偏好"""
    config = Config(data_dir=tmp_path / "data", token="test")
    app = create_app(config)
    with TestClient(app) as client:
        path = "/api/settings/recruitment"
        assert client.get(path).status_code == 401
        assert client.get(path, headers=HEADERS).json() == {"import_policy": "keep"}
        assert (
            client.put(path, headers=HEADERS, json={"import_policy": "invalid"}).status_code == 422
        )
        assert client.get(path, headers=HEADERS).json() == {"import_policy": "keep"}
        saved = client.put(path, headers=HEADERS, json={"import_policy": "update"})
        assert saved.status_code == 200
        assert saved.json() == {"import_policy": "update"}
        data = sample()
        first = client.post(
            "/api/recruitment/import", headers=HEADERS, json=import_body(data)
        ).json()
        data["bookmarks"][0]["notes"] = "按设置更新备注"
        policy = client.get(path, headers=HEADERS).json()["import_policy"]
        body = import_body(data, first["snapshot"]["revision"], policy)
        preview = client.post("/api/recruitment/import/preview", headers=HEADERS, json=body).json()
        assert preview["updated"] == 1
        client.put(path, headers=HEADERS, json={"import_policy": "keep"})
        result = client.post("/api/recruitment/import", headers=HEADERS, json=body).json()
        assert result["snapshot"]["data"]["bookmarks"][0]["notes"] == "按设置更新备注"
        assert "import_policy" not in client.get("/api/recruitment/export", headers=HEADERS).json()
        client.put(path, headers=HEADERS, json={"import_policy": "update"})
    with TestClient(create_app(config)) as client:
        assert client.get(path, headers=HEADERS).json() == {"import_policy": "update"}
    archive = create_backup(app.state.services.db, config.data_dir)
    restored = tmp_path / "restored"
    restore_backup(archive, restored)
    with TestClient(create_app(Config(data_dir=restored, token="test"))) as client:
        assert client.get(path, headers=HEADERS).json() == {"import_policy": "update"}
