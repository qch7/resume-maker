import httpx
import pytest

from resume_maker.infrastructure.database import Database
from resume_maker.integrations.sources import capture_evidence, project_sources
from resume_maker.services.catalog import Catalog


@pytest.fixture(autouse=True)
def isolate_model_network(monkeypatch, tmp_path):
    """测试不加载用户供应商凭据，真实网络出口始终由模拟传输替代"""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "isolated-codex"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def blocked(*args, **kwargs):
        """任何遗漏模拟传输的外网调用立即失败"""
        pytest.fail("测试禁止连接真实模型服务，请注入 MockTransport")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)

    def blocked_cli(*args, **kwargs):
        """默认禁止真实 CLI 模型请求，单测必须显式注入执行替身"""
        pytest.fail("测试禁止启动真实模型会话，请注入 CLI runner")

    monkeypatch.setattr("resume_maker.integrations.providers.codex.run_cli", blocked_cli)


@pytest.fixture(autouse=True)
def isolate_template_visual_renderer(monkeypatch):
    """单元测试不启动桌面 Word，整页证据测试显式注入 PDF，真实排版另做本机验收"""
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
    """在临时数据目录创建业务服务，让每个测试的数据相互隔离"""
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
    """构造含两条亮点的最小经历，用于测试保存、排序和固定引用"""
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
    """将示例经历发布为正式修订，作为后续测试的已保存基线"""
    base = project["head_revision"]
    catalog.put_draft(project["id"], base, "experience", experience(), 0)
    return catalog.save_revision(project["id"], base, base)
