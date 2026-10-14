"""通用资料来源的边界、同事务快照、缺包保留"""

import sqlite3
from copy import deepcopy

import pytest

from resume_maker.core.errors import Problem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.infrastructure.database import Database
from resume_maker.plugin_packages.sys_resume.services.resume_sources import ResumeSources
from resume_maker.runtime.host import Contribution
from resume_maker.sdk.sources import ResumeSource, SourceField, SourceItem, SourcePage


def test_sources_share_read_transaction_and_keep_local_layout(tmp_path):
    """来源只改所属内容，未知来源、本地编排保留，旧读取句柄不能继续调用"""
    db = Database(tmp_path / "data.db")
    db.set_setting("community.example:item", "已核对")
    readers = []

    def resolve(reader, ids):
        """使用当前保存事务中的新值，不另外打开连接"""
        readers.append(reader)
        return (
            SourceItem(
                id=ids[0],
                version="2",
                title=reader.setting("community.example:item"),
                custom_fields=(SourceField(id="extra", label="原标题", value="来源值"),),
            ),
        )

    contribution = Contribution(
        "community.example",
        "resume.sources",
        "community.example/items",
        ResumeSource("合成资料", "1.0.0", lambda *_args: SourcePage(items=()), resolve),
    )
    entries = [contribution]
    registry = ResumeSources(db, lambda _point: tuple(entries))
    document = ResumeDocument.model_validate(
        {
            "sections": [
                {"id": "projects", "kind": "projects", "title": "项目"},
                {
                    "id": "education",
                    "title": "教育",
                    "entries": [
                        {
                            "id": "entry",
                            "title": "旧值",
                            "visible": False,
                            "source": {
                                "provider": "community.example/items",
                                "id": "synthetic",
                                "version": "1",
                            },
                            "custom_fields": [
                                {"id": "note", "label": "备注", "value": "手工备注"},
                                {
                                    "id": "extra",
                                    "label": "自定标签",
                                    "value": "旧",
                                    "visible": True,
                                },
                            ],
                            "field_definitions": [
                                {"id": "extra", "label": "自定标签", "visible": True}
                            ],
                        },
                        {
                            "id": "unknown",
                            "title": "缺包内容",
                            "source": {
                                "provider": "missing.source/items",
                                "id": "1",
                                "version": "1",
                            },
                        },
                    ],
                },
            ]
        }
    ).model_dump()
    before = deepcopy(document)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE settings SET value_json='\"同一事务\"' WHERE key=?", ("community.example:item",)
        )
        result = registry.resolve(document, conn)
        assert result["sections"][1]["entries"][0]["title"] == "同一事务"
    assert document == before
    entry = result["sections"][1]["entries"][0]
    assert entry["source"]["version"] == "2"
    assert entry["visible"] is False
    assert entry["custom_fields"][0]["value"] == "手工备注"
    assert entry["custom_fields"][1] == {
        "id": "extra",
        "label": "自定标签",
        "value": "来源值",
        "visible": True,
    }
    assert result["sections"][1]["entries"][1] == before["sections"][1]["entries"][1]
    with pytest.raises(Problem, match="关闭"):
        readers[0].setting("community.example:item")
    entries.clear()
    assert registry.resolve(result) == result


def test_source_query_cannot_write_and_bad_pagination_is_rejected(tmp_path):
    """查询失败不产生半次写入，重复来源身份不能进入选择列表"""
    db = Database(tmp_path / "data.db")

    def bad(reader, *_args):
        """模拟误用读取接口写入数据的来源插件"""
        reader.all("INSERT INTO settings VALUES ('wrong','1')")
        return SourcePage(items=())

    entries = [
        Contribution(
            "community.example",
            "resume.sources",
            "community.example/items",
            ResumeSource("合成资料", "1.0.0", bad, lambda *_args: ()),
        )
    ]
    registry = ResumeSources(db, lambda _point: entries)
    with pytest.raises(sqlite3.DatabaseError):
        registry.browse("community.example/items")
    assert db.setting("wrong") is None
    row = SourceItem(id="duplicate", version="1", title="合成")
    entries[0] = Contribution(
        "community.example",
        "resume.sources",
        "community.example/items",
        ResumeSource(
            "合成资料", "1.0.0", lambda *_args: SourcePage(items=(row, row)), lambda *_args: ()
        ),
    )
    with pytest.raises(Problem, match="重复"):
        registry.browse("community.example/items")


def test_many_documents_share_resolution_but_keep_independent_layouts(tmp_path):
    """重复引用按提供方去重，多份简历的顺序、标签、显隐及引用副本独立"""
    db = Database(tmp_path / "data.db")
    calls, readers = [], []

    def resolve(reader, ids):
        """只发布仍存在的确认条目，缺失项由简历保留旧快照"""
        calls.append(ids)
        readers.append(reader)
        return (
            SourceItem(
                id="shared",
                version="2",
                title="来源新值",
                custom_fields=(SourceField(id="extra", label="来源标签", value="新字段值"),),
            ),
        )

    entry = {
        "id": "entry",
        "title": "旧值",
        "visible": False,
        "hidden_fields": ["details"],
        "source": {"provider": "community.example/items", "id": "shared", "version": "1"},
        "custom_fields": [{"id": "note", "label": "备注", "value": "手工内容"}],
        "field_definitions": [{"id": "extra", "label": "第一份标签", "visible": False}],
    }
    missing = {**deepcopy(entry), "id": "missing", "title": "缺失快照"}
    missing["source"]["id"] = "missing"
    unknown = {**deepcopy(entry), "id": "unknown", "title": "缺包快照"}
    unknown["source"]["provider"] = "missing.source/items"
    document = ResumeDocument(
        sections=[
            {"id": "projects", "kind": "projects", "title": "项目"},
            {"id": "linked", "title": "第一份栏目", "entries": [entry, missing, unknown]},
        ]
    ).model_dump()
    other = deepcopy(document)
    other["sections"][1]["title"] = "第二份栏目"
    other_entry = other["sections"][1]["entries"][0]
    other_entry["visible"] = True
    other_entry["hidden_fields"] = []
    other_entry["field_definitions"][0]["label"] = "第二份标签"
    other["sections"][1]["entries"].reverse()
    before, other_before = deepcopy(document), deepcopy(other)
    contribution = Contribution(
        "community.example",
        "resume.sources",
        "community.example/items",
        ResumeSource("合成资料", "1.0.0", lambda *_: SourcePage(items=()), resolve),
    )
    registry = ResumeSources(db, lambda _: [contribution])
    first, second, repeated, empty = registry.resolve_many([document, other, document, None])
    assert calls == [("shared", "missing")]
    assert document == before and other == other_before and empty is None
    assert first == repeated and first is not repeated
    assert second["sections"][1]["title"] == "第二份栏目"
    left = first["sections"][1]["entries"][0]
    right = second["sections"][1]["entries"][-1]
    assert left["title"] == right["title"] == "来源新值"
    assert left["source"]["version"] == right["source"]["version"] == "2"
    assert left["visible"] is False and right["visible"] is True
    assert left["hidden_fields"] == ["details"] and right["hidden_fields"] == []
    assert left["custom_fields"][-1]["label"] == "第一份标签"
    assert right["custom_fields"][-1]["label"] == "第二份标签"
    assert left["custom_fields"][0]["value"] == "手工内容"
    assert first["sections"][1]["entries"][1:] == before["sections"][1]["entries"][1:]
    left["source"]["version"] = "local edit"
    left["custom_fields"][-1]["value"] = "独立修改"
    assert right["source"]["version"] == "2"
    assert repeated["sections"][1]["entries"][0]["custom_fields"][-1]["value"] == "新字段值"
    with pytest.raises(Problem, match="关闭"):
        readers[0].setting("unused")


@pytest.mark.parametrize("returned", ["unknown", "duplicate"])
def test_many_documents_reject_invalid_source_results_without_changing_inputs(tmp_path, returned):
    """批量解析继续拒绝越界或重复身份，失败不能修改任何输入简历"""
    db = Database(tmp_path / "data.db")
    document = {
        "sections": [
            {
                "entries": [
                    {
                        "title": "旧快照",
                        "source": {
                            "provider": "community.example/items",
                            "id": "shared",
                            "version": "1",
                        },
                    }
                ]
            }
        ]
    }
    original = deepcopy(document)
    row = SourceItem(id="unknown" if returned == "unknown" else "shared", version="2", title="新值")
    contribution = Contribution(
        "community.example",
        "resume.sources",
        "community.example/items",
        ResumeSource(
            "合成资料",
            "1.0.0",
            lambda *_: SourcePage(items=()),
            lambda *_: (row, row) if returned == "duplicate" else (row,),
        ),
    )
    registry = ResumeSources(db, lambda _: [contribution])
    with pytest.raises(Problem):
        registry.resolve_many([document, document])
    assert document == original
