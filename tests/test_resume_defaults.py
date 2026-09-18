"""默认栏目设置持久化、并发保护和排版一致性。"""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.experience import displayed_experience
from resume_maker.domain.models import DefaultField, ProjectVisibility


def defaults():
    """构造含个人自定义项及教育字段的默认配置。"""
    return {
        "version": 0,
        "personal_fields": [
            {"id": "name", "label": "姓名", "visible": True},
            {"id": "default:wechat", "label": "微信", "visible": True},
        ],
        "sections": [
            {"id": "projects", "title": "项目经历", "kind": "projects", "fields": []},
            {
                "id": "education",
                "title": "教育经历",
                "kind": "education",
                "fields": [
                    {"id": "title", "label": "学校", "visible": True},
                    {"id": "default:tutor", "label": "导师", "visible": False},
                ],
            },
        ],
    }


def test_defaults_persist_across_application_restarts_and_reject_stale_writes(tmp_path):
    """设置随数据库持久化，多窗口不能覆盖较新的设置。"""
    config = Config(data_dir=tmp_path, token="test")
    headers = {"x-resume-token": "test"}
    with TestClient(create_app(config)) as client:
        assert client.get("/api/settings/resume-defaults", headers=headers).json() is None
        saved = client.put("/api/settings/resume-defaults", headers=headers, json=defaults())
        assert saved.status_code == 200
        assert saved.json()["version"] == 1
        assert (
            client.put(
                "/api/settings/resume-defaults", headers=headers, json=defaults()
            ).status_code
            == 409
        )
        assert client.get("/api/state", headers=headers).json()["resume_defaults"] == saved.json()
        assert client.put("/api/settings/resume-defaults", json=saved.json()).status_code == 401
    with TestClient(create_app(config)) as client:
        assert client.get("/api/settings/resume-defaults", headers=headers).json() == saved.json()


@pytest.mark.parametrize("case", ["duplicate", "unknown", "blank", "projects", "cycle", "capacity"])
def test_invalid_default_definitions_are_rejected_without_saving(tmp_path, case):
    """校验字段和层级，失败不会留下部分配置。"""
    body = defaults()
    if case == "duplicate":
        body["personal_fields"].append(body["personal_fields"][0])
    elif case == "unknown":
        body["personal_fields"][0]["id"] = "unsupported"
    elif case == "blank":
        body["sections"][0]["title"] = " "
    elif case == "projects":
        body["sections"].pop(0)
    elif case == "cycle":
        body["sections"][1]["parent_id"] = "education"
    else:
        body["personal_fields"] = [{"id": f"default:{i}", "label": "信息"} for i in range(21)]
    headers = {"x-resume-token": "test"}
    with TestClient(create_app(Config(data_dir=tmp_path, token="test"))) as client:
        assert (
            client.put("/api/settings/resume-defaults", headers=headers, json=body).status_code
            == 422
        )
        assert client.get("/api/settings/resume-defaults", headers=headers).json() is None


def test_removed_project_defaults_stay_hidden_in_export_without_changing_revision():
    """已删除的默认项不能被历史显隐覆盖打开，排版副本不修改项目版本。"""
    original = {
        "title": "项目",
        "period": "2026",
        "role": "开发",
        "stack": ["Python"],
        "description": "说明",
        "highlights": [],
        "custom_fields": [
            {"id": "default:removed", "label": "旧备注", "value": "保留原文", "visible": True},
            {"id": "default:kept", "label": "旧名称", "value": "演示地址", "visible": True},
        ],
    }
    before = deepcopy(original)
    definitions = [
        DefaultField(id="title", label="项目名称"),
        DefaultField(id="default:kept", label="演示链接"),
    ]
    visible = displayed_experience(
        original,
        ProjectVisibility(fields={"role": True}, custom_fields={"default:removed": True}),
        definitions,
    )
    assert visible["title"] == "项目"
    assert visible["role"] == ""
    assert visible["stack"] == []
    assert visible["custom_fields"][0]["visible"] is False
    assert visible["custom_fields"][1]["label"] == "演示链接"
    assert original == before
