"""多窗口交错时确认结果和导出内容必须属于提交方"""

from contextlib import contextmanager

import pytest

from resume_maker.core.errors import Problem
from resume_maker.plugin_packages.sys_resume.services.resumes import Resumes
from tests.support.data import experience
from tests.support.document_services import Documents
from tests.support.documents import resume_content


def test_draft_confirmation_precedes_another_windows_write(catalog, project, monkeypatch):
    """事务退出后另一个窗口写入，第一窗口只能拿到自己的确认版本"""
    transaction = catalog.db.transaction
    interleave = True
    base = project["head_revision"]

    @contextmanager
    def write_then_interleave():
        """确定性插入第二次提交，覆盖旧实现的事务后读取窗口"""
        nonlocal interleave
        with transaction() as conn:
            yield conn
        if interleave:
            interleave = False
            catalog.put_draft(project["id"], base, "experience", experience("窗口乙"), 1)

    monkeypatch.setattr(catalog.db, "transaction", write_then_interleave)
    confirmed = catalog.put_draft(project["id"], base, "experience", experience("窗口甲"), 0)
    assert confirmed["content"]["title"] == "窗口甲"
    assert confirmed["drafts"][0]["version"] == 1
    assert catalog.working(project["id"], base)["content"]["title"] == "窗口乙"
    with pytest.raises(Problem) as failure:
        catalog.put_draft(project["id"], base, "experience", experience("甲下一次输入"), 1)
    assert failure.value.status == 409


def test_export_rejects_changed_version_without_publishing(catalog, tmp_path):
    """保存与导出之间方案变化时不生成他人内容、不发布记录或文件"""
    resumes = Resumes(catalog, storage=catalog.db, assets=catalog.assets)
    content = resume_content()
    first = resumes.save_resume("窗口甲", None, [], document=content)
    second = resumes.save_resume("窗口乙", None, [], first["id"], first["version"], content)
    documents = Documents(
        resumes, tmp_path / "data", render=None, storage=catalog.db, assets=catalog.assets
    )
    with pytest.raises(Problem) as failure:
        documents.export(first["id"], expected_version=first["version"])
    assert failure.value.status == 409
    assert catalog.db.all("SELECT * FROM exports") == []
    assert (
        resumes.freeze_export(tmp_path / "data", first["id"], second["version"]).values()[0]["name"]
        == "窗口乙"
    )
