"""合成经历、项目来源和正文读取辅助函数"""

from docx import Document

from resume_maker.integrations.sources import capture_evidence, project_sources
from resume_maker.integrations.word.ooxml import w
from resume_maker.integrations.word.templates.mapping import paragraph_text
from resume_maker.services.workspace import Workspace


def record_source_files(db, data_dir, project, paths=("README.md",)):
    """仅为测试指定的来源文件建立证据记录以免夹具依赖已经移除的整库采集"""
    return capture_evidence(
        db,
        data_dir,
        project,
        project_sources(project),
        [{"source": "source-0", "path": path, "status": "document"} for path in paths],
    )


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


def body_text(path):
    """按段落拼接文字，标签和内容允许分属不同字重的文字运行"""
    return "\n".join(paragraph_text(node) for node in Document(path).element.body.iter(w("p")))


def project_info():
    """固定项和自定义项各含可见和隐藏内容，便于验证恢复不丢原值"""
    return {
        **experience("项目标题原值"),
        "period": "2025.01–2026.02",
        "role": "角色原值",
        "hidden_fields": ["role", "stack"],
        "custom_fields": [
            {
                "id": "link",
                "label": "项目链接",
                "value": "https://example.test/project",
                "visible": True,
            },
            {"id": "team", "label": "团队", "value": "隐藏团队原值", "visible": False},
            {"id": "blank", "label": "空白条目", "value": " ", "visible": True},
        ],
    }


def make_sources(tmp_path):
    """创建含不同源码文件的两个独立子项目以免读取真实源码"""
    roots = [tmp_path / "agent", tmp_path / "rag"]
    for root in roots:
        root.mkdir()
        (root / f"{root.name}.py").write_text(f"NAME = '{root.name}'\n", encoding="utf-8")
    return [str(root.resolve()) for root in roots]


def children(catalog, parent_id):
    """通过工作台公开数据按来源定位子项目"""
    return {
        p["roots"][0]: p
        for p in Workspace(catalog).state()["projects"]
        if p["parent_id"] == parent_id
    }
