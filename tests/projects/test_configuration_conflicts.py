"""项目配置保存拒绝旧窗口并返回本次事务确认"""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.domain.models import ProjectProfile
from resume_maker.plugin_packages.sys_experience.services.projects import Projects


def test_profile_rejects_stale_form_and_confirms_own_write(catalog, project, monkeypatch):
    """本人贡献的日期不会被旧角色表单清空，确认不借用后续内容"""
    projects = Projects(catalog)
    original = ProjectProfile.model_validate(project["profile"])
    saved = projects.save_profile(
        project["id"], original.model_copy(update={"period": "乙日期"}), original
    )
    with pytest.raises(Problem) as failure:
        projects.save_profile(
            project["id"], original.model_copy(update={"role": "甲角色"}), original
        )
    assert failure.value.status == 409
    assert catalog.project(project["id"])["profile"]["period"] == "乙日期"
    transaction = catalog.db.transaction
    interleave = True
    baseline = ProjectProfile.model_validate(saved["profile"])

    @contextmanager
    def write_then_interleave():
        """提交后模拟第二窗口用本次结果继续保存"""
        nonlocal interleave
        with transaction() as conn:
            yield conn
        if interleave:
            interleave = False
            projects.save_profile(
                project["id"],
                baseline.model_copy(update={"role": "丙角色"}),
                baseline.model_copy(update={"role": "甲角色"}),
            )

    monkeypatch.setattr(catalog.db, "transaction", write_then_interleave)
    confirmed = projects.save_profile(
        project["id"], baseline.model_copy(update={"role": "甲角色"}), baseline
    )
    assert confirmed["profile"]["role"] == "甲角色"
    assert catalog.project(project["id"])["profile"]["role"] == "丙角色"


def test_sources_reject_stale_form_without_changing_group(catalog, tmp_path):
    """旧来源配置不能覆盖新名称、目录及父子关系"""
    roots = [tmp_path / "a", tmp_path / "b", tmp_path / "c"]
    for root in roots:
        root.mkdir()
    project = catalog.create_project("原项目", [str(roots[0]), str(roots[1])])
    projects = Projects(catalog)
    saved = projects.update_sources(
        project["id"], "乙项目", [str(roots[2])], project["name"], project["roots"]
    )
    with pytest.raises(Problem) as failure:
        projects.update_sources(
            project["id"], "甲项目", project["roots"], project["name"], project["roots"]
        )
    assert failure.value.status == 409
    current = catalog.project(project["id"])
    assert (current["name"], current["roots"]) == (saved["name"], saved["roots"])
    assert not catalog.db.all("SELECT * FROM project_hierarchy WHERE parent_id=?", (project["id"],))


def test_project_http_requires_baselines_and_reports_conflicts(tmp_path):
    """HTTP 拒绝缺失基线及旧表单，资料继续保留最新保存"""
    config = Config(data_dir=tmp_path / "data")
    with TestClient(create_app(config)) as client:
        headers = {"x-resume-token": config.token}
        project = client.post(
            "/api/projects", headers=headers, json={"name": "合成", "roots": []}
        ).json()
        path = f"/api/projects/{project['id']}"
        baseline = project["profile"]
        assert client.put(path + "/profile", headers=headers, json=baseline).status_code == 422
        saved = client.put(
            path + "/profile",
            headers=headers,
            json={"profile": {**baseline, "role": "乙"}, "expected_profile": baseline},
        )
        assert saved.status_code == 200
        assert (
            client.put(
                path + "/profile",
                headers=headers,
                json={"profile": baseline, "expected_profile": baseline},
            ).status_code
            == 409
        )
        assert (
            client.put(
                path + "/sources", headers=headers, json={"name": "甲", "roots": []}
            ).status_code
            == 422
        )
        assert (
            client.put(
                path + "/sources",
                headers=headers,
                json={
                    "name": "乙",
                    "roots": [],
                    "expected_name": project["name"],
                    "expected_roots": [],
                },
            ).status_code
            == 200
        )
        assert (
            client.put(
                path + "/sources",
                headers=headers,
                json={
                    "name": "甲",
                    "roots": [],
                    "expected_name": project["name"],
                    "expected_roots": [],
                },
            ).status_code
            == 409
        )
