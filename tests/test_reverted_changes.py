"""恢复基线内容的草稿不展示未提交节点，也不生成无效版本。"""

from copy import deepcopy

import pytest

from resume_maker.domain.experience import field_value, same_experience
from resume_maker.domain.project_layout import project_body_order
from resume_maker.services.projects import Projects


@pytest.mark.parametrize("field", ["meta", "order", "highlight:one"])
def test_reverted_draft_not_in_history_or_new_versions(catalog, project, populated, field):
    """已自动保存过的文字或排序改回原值，保留并发记录但历史树和版本均无差异。"""
    identifier, revision = project["id"], populated["id"]
    base = populated["content"]
    original = field_value(base, field)
    if field == "meta":
        changed = {**original, "role": "临时角色", "body_order": ["highlights", "description"]}
    elif field == "order":
        changed = list(reversed(original))
    else:
        changed = {**original, "text": "临时正文"}
    catalog.put_draft(identifier, revision, field, changed, 0)
    assert len(Projects(catalog).uncommitted(identifier)) == 1
    catalog.put_draft(identifier, revision, field, original, 1)
    assert Projects(catalog).uncommitted(identifier) == []
    assert same_experience(catalog.working(identifier, revision)["content"], base)
    assert catalog.save_revision(identifier, revision, revision)["id"] == revision


def test_equivalent_explicit_order_does_not_create_versions(catalog, project, populated):
    """已保存的明确排序可忽略失效自定义标识，不制造无意义的新版本。"""
    identifier, revision = project["id"], populated["id"]
    base = populated["content"]
    catalog.put_draft(identifier, revision, "meta", {"body_order": project_body_order(base)}, 0)
    saved = catalog.save_revision(identifier, revision, revision)
    revision, base = saved["id"], saved["content"]
    content = deepcopy(base)
    content["body_order"] = ["custom:missing", *project_body_order(base)]
    assert same_experience(content, base)
    catalog.put_draft(identifier, revision, "meta", field_value(content, "meta"), 0)
    assert Projects(catalog).uncommitted(identifier) == []
    assert catalog.save_revision(identifier, revision, revision)["id"] == revision


def test_explicit_default_order_can_replace_legacy_resume_order(catalog, project, populated):
    """旧版可能从简历继承不同顺序，用户明确改成默认顺序时仍需保存一个版本。"""
    identifier, revision = project["id"], populated["id"]
    base = populated["content"]
    value = {**base, "body_order": project_body_order(base)}
    assert not same_experience(value, base)
    catalog.put_draft(identifier, revision, "meta", field_value(value, "meta"), 0)
    assert catalog.save_revision(identifier, revision, revision)["id"] != revision


def test_reverted_field_does_not_hide_other_changes(catalog, project, populated):
    """一项恢复基线后仍应显示并提交其他真实修改。"""
    identifier, revision = project["id"], populated["id"]
    base = populated["content"]
    catalog.put_draft(identifier, revision, "meta", {"role": "仍需提交"}, 0)
    catalog.put_draft(identifier, revision, "order", ["two", "one"], 0)
    catalog.put_draft(identifier, revision, "order", ["one", "two"], 1)
    assert len(Projects(catalog).uncommitted(identifier)) == 1
    saved = catalog.save_revision(identifier, revision, revision)
    assert saved["id"] != revision
    assert saved["content"]["role"] == "仍需提交"
    assert saved["content"]["highlights"] == base["highlights"]
