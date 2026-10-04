"""补充隐私规则不会移除基础保护，变更后旧材料停止外发"""

import threading

import pytest

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import Database, dump
from resume_maker.infrastructure.privacy_contributions import PrivacyContributions
from resume_maker.integrations.privacy_gateway import PrivacyCancellation
from resume_maker.integrations.privacy_store import PrivacyStore
from resume_maker.runtime.host import Contribution
from resume_maker.sdk.privacy import PrivacyRuleContribution, PrivacyValues


def test_extra_rules_protect_material_and_cancel_changed_context(tmp_path):
    """插件补充词和系统邮箱规则同时生效，规则变化使旧取消句柄失效"""
    db = Database(tmp_path / "resume.db")
    terms = ["合成内部标识"]
    rule = PrivacyRuleContribution(
        "合成保护", "补充本机词", "1.0.0", lambda _reader: PrivacyValues(terms=tuple(terms))
    )
    entries = [
        Contribution(
            "community.example", "privacy.rule_contributions", "community.example/rules", rule
        )
    ]
    rules = PrivacyContributions(db, lambda _point: entries)
    store = PrivacyStore(db, rules)
    redactor = store.redactor()
    original = "合成内部标识 sample@example.test"
    redacted = redactor.prompt(original)
    assert "合成内部标识" not in redacted and "sample@example.test" not in redacted
    assert redactor.restore(redacted) == original
    assert "合成内部标识" not in dump(rules.describe())
    flag = PrivacyCancellation(threading.Event(), store)
    assert not flag.is_set()
    terms.append("新增保护")
    assert flag.is_set()
    entries.clear()
    assert "sample@example.test" not in store.redactor().prompt("sample@example.test")


def test_rule_failure_blocks_outgoing_data_without_exposing_error_text(tmp_path):
    """插件异常不得被吞掉或回显敏感正文"""
    db = Database(tmp_path / "resume.db")

    def broken(_reader):
        """模拟规则读取失败，异常正文不能出现在用户可见错误中"""
        raise ValueError("合成敏感正文")

    entry = Contribution(
        "community.example",
        "privacy.rule_contributions",
        "community.example/rules",
        PrivacyRuleContribution("合成", "", "1.0.0", broken),
    )
    store = PrivacyStore(db, PrivacyContributions(db, lambda _point: [entry]))
    with pytest.raises(Problem, match="阻止") as error:
        store.redactor()
    assert "合成敏感正文" not in str(error.value)


def test_retained_privacy_descriptor_protects_missing_plugin_data(tmp_path):
    """持久资料描述不执行插件代码，停用或缺包仍登记结构化身份及凭据"""
    db = Database(tmp_path / "resume.db")
    db.set_setting(
        "community.example:private",
        {"personal": {"name": "合成用户甲"}, "api_key": "synthetic-private-key"},
    )
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO plugin_data_catalog VALUES (?,?,?,?)",
            (
                "community.example",
                1,
                dump({"privacy_settings": ["community.example:"]}),
                "1.0.0",
            ),
        )
    redactor = PrivacyStore(db).redactor()
    value = redactor.prompt("合成用户甲 synthetic-private-key")
    assert "合成用户甲" not in value and "synthetic-private-key" not in value
    assert "synthetic-private-key" not in redactor.restore(value)
