"""验证请求内匹配缓存的复用、规则变更及凭据不可恢复"""

import pytest

from resume_maker.integrations import privacy
from resume_maker.integrations.privacy import Redactor
from resume_maker.integrations.privacy_terms import PrivacyTerms
from resume_maker.sdk.model import ProviderError


def test_fixed_terms_are_prepared_once_until_content_changes(monkeypatch):
    """多段普通文字复用匹配器，同数量规则替换后立即保护新身份"""
    calls, original = [], privacy.literal_pattern

    def counted(value):
        """统计敏感词规则准备，避免用耗时阈值制造不稳定测试"""
        calls.append(value)
        return original(value)

    monkeypatch.setattr(privacy, "literal_pattern", counted)
    redactor = Redactor([f"SyntheticIdentity{index:04}" for index in range(100)])
    assert redactor.text("ordinary code") == "ordinary code"
    prepared = len(calls)
    for _ in range(100):
        assert redactor.text("ordinary code") == "ordinary code"
    assert len(calls) == prepared
    redactor.values.discard("SyntheticIdentity0000")
    redactor.values.add("NewSyntheticIdentity")
    value = "NewSyntheticIdentity"
    assert redactor.restore(redactor.text(value)) == value
    assert value not in redactor.text(value)
    assert len(calls) > prepared


def test_new_mapping_and_secrets_are_applied_to_cached_restoration():
    """映射增量可立即还原，后来登记的凭据不能从既有占位符恢复"""
    redactor = Redactor(["SyntheticIdentity"])
    first = redactor.text("SyntheticIdentity")
    assert redactor.restore([{"name": first}]) == [{"name": "SyntheticIdentity"}]
    second = redactor.token("AnotherIdentity")
    assert redactor.restore(second) == "AnotherIdentity"
    redactor.secrets.update(["SyntheticIdentity", "AnotherIdentity"])
    assert redactor.restore([first, second]) == ["[凭据已移除]", "[凭据已移除]"]
    with pytest.raises(ProviderError, match="未知"):
        redactor.restore("[[RM_000000000000_1]]")


@pytest.mark.parametrize(
    "operation,expected",
    [
        (lambda values: values.add("third"), {"first", "second", "third"}),
        (lambda values: values.update(["third"]), {"first", "second", "third"}),
        (lambda values: values.discard("first"), {"second"}),
        (lambda values: values.remove("first"), {"second"}),
        (lambda values: values.clear(), set()),
        (lambda values: values.difference_update(["first"]), {"second"}),
        (lambda values: values.intersection_update(["first"]), {"first"}),
        (
            lambda values: values.symmetric_difference_update(["first", "third"]),
            {"second", "third"},
        ),
        (lambda values: values.__ior__({"third"}), {"first", "second", "third"}),
        (lambda values: values.__iand__({"first"}), {"first"}),
        (lambda values: values.__isub__({"first"}), {"second"}),
        (lambda values: values.__ixor__({"first", "third"}), {"second", "third"}),
    ],
)
def test_all_public_term_mutations_invalidate_generation(operation, expected):
    """集合兼容入口发生变化后必须撤销缓存，防止新规则漏检"""
    terms = PrivacyTerms(["first", "second"])
    before = terms.generation
    operation(terms)
    assert terms == expected and terms.generation > before


def test_repeated_terms_keep_generation_and_pop_invalidates():
    """重复登记不反复重建匹配器，移除任意规则仍会失效"""
    terms = PrivacyTerms(["first"])
    terms.update(["first"])
    terms.discard("missing")
    assert terms.generation == 0
    assert terms.pop() == "first" and terms.generation > 0
