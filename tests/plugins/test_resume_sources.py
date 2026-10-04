"""通用资料来源的边界、同事务快照和缺包保留"""

import sqlite3
from copy import deepcopy

import pytest

from resume_maker.core.errors import Problem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.infrastructure.database import Database
from resume_maker.runtime.host import Contribution
from resume_maker.sdk.sources import ResumeSource, SourceField, SourceItem, SourcePage
from resume_maker.services.resume_sources import ResumeSources


def test_sources_share_read_transaction_and_keep_local_layout(tmp_path):
    """来源只改所属内容，未知来源和本地编排保留，旧读取句柄不能继续调用"""
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
