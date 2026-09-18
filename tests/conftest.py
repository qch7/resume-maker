import pytest

from resume_maker.infrastructure.database import Database
from resume_maker.integrations.sources import capture_evidence, project_sources
from resume_maker.services.catalog import Catalog


@pytest.fixture(autouse=True)
def isolate_template_visual_renderer(monkeypatch):
    """单元测试不启动桌面 Word；整页证据测试显式注入 PDF；真实排版另做本机验收"""
    monkeypatch.setattr(
        "resume_maker.integrations.word.templates.visuals.word_process",
        lambda *_: "测试环境未启动 Word",
    )


def record_source_files(db, data_dir, project, paths=("README.md",)):
    """仅为测试指定的来源文件建立证据记录以免夹具依赖已经移除的整库采集"""
    return capture_evidence(
        db,
        data_dir,
        project,
        project_sources(project),
        [{"source": "source-0", "path": path, "status": "document"} for path in paths],
    )


@pytest.fixture
def catalog(tmp_path):
    """在临时数据目录创建业务服务；让每个测试的数据相互隔离"""
    return Catalog(Database(tmp_path / "data" / "resume.db"))


@pytest.fixture
def project(catalog, tmp_path):
    """在临时目录登记示例源码项目以免测试访问用户真实来源"""
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text(
        "# Example\nA project for document processing.\n", encoding="utf-8"
    )
    return catalog.create_project("Example", [str(source)])


def experience(title="Example"):
    """构造含两条亮点的最小经历；用于测试保存、排序和固定引用"""
    return {
        "title": title,
        "period": "",
        "role": "",
        "stack": ["Python"],
        "description": "Document processing",
        "body_order": None,
        "highlights": [
            {"id": "one", "title": "Parser", "text": "Parse documents", "evidence": []},
            {"id": "two", "title": "Export", "text": "Export Word", "evidence": []},
        ],
    }


@pytest.fixture
def populated(catalog, project):
    """将示例经历发布为正式修订；作为后续测试的已保存基线"""
    base = project["head_revision"]
    catalog.put_draft(project["id"], base, "experience", experience(), 0)
    return catalog.save_revision(project["id"], base, base)
