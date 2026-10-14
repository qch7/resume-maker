"""验证请求内匹配缓存的复用、规则变更及凭据不可恢复"""

import random

import pytest

from resume_maker.integrations import privacy
from resume_maker.integrations.privacy import Redactor
from resume_maker.integrations.privacy_terms import PrivacyTerms
from resume_maker.integrations.privacy_text import literal_spans
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


def test_distinct_contacts_do_not_rebuild_fixed_matcher(monkeypatch):
    """不同动态联系方式只准备自身候选，大量固定规则不会逐段重建"""
    prepared, original = [], privacy.literal_pattern

    def counted(value):
        """按候选准备次数约束复杂度，避免依赖机器运行速度"""
        prepared.append(value)
        return original(value)

    monkeypatch.setattr(privacy, "literal_pattern", counted)
    redactor = Redactor([f"SyntheticIdentity{index:04}" for index in range(1000)])
    for index in range(200):
        original_text = f"联系：person{index}@example.invalid"
        safe = redactor.text(original_text)
        assert f"person{index}@example.invalid" not in safe
        assert redactor.restore(safe) == original_text
    assert sum(value.startswith("SyntheticIdentity") for value in prepared) == 1000
    assert len(prepared) == 1200


def test_split_matchers_keep_combined_longest_and_overlap_semantics():
    """独立候选流使用正则联合表达式作参照，覆盖相互遮挡后的继续位置"""
    randomizer = random.Random(47)
    cases = [
        ("abcde", {"abc"}, {"bcde", "de"}),
        ("abcdabcd", {"ab", "abcd"}, {"abc", "cd"}),
        ("21 2021 value21 0.21 ２１", {"21"}, {"２１", "2021"}),
        ("星桥\n测试大学 星 桥", {"星桥"}, {"星桥\n测试大学", "星 桥"}),
    ]
    for _ in range(600):
        text = "".join(randomizer.choices("abc 12", k=80))
        values = {
            text[start : start + randomizer.randint(1, 8)]
            for start in randomizer.sample(range(70), 12)
        }
        fixed = set(randomizer.sample(sorted(values), len(values) // 2))
        cases.append((text, fixed, values - fixed))
    for text, fixed, dynamic in cases:
        combined = Redactor.pattern(fixed | dynamic)
        expected = [match.span() for match in combined.finditer(text)]
        actual = list(literal_spans(text, Redactor.pattern(fixed), Redactor.pattern(dynamic)))
        assert actual == expected, (text, fixed, dynamic, actual, expected)


@pytest.mark.parametrize(
    "known,text",
    [
        (["person"], "person@example.invalid"),
        (["contact person@"], "contact person@example.invalid"),
        (["21"], "21 person21@example.invalid value21 0.21"),
        (["星桥测试大学"], "联系：person@example.invalid；星桥\n测试大学"),
        (["http"], "https://example.invalid/person@example.invalid"),
    ],
)
def test_dynamic_matches_restore_exact_text_with_overlapping_fixed_rules(known, text):
    """动态格式、固定敏感词存在重叠时仍精确还原，完整邮箱不会露出后缀"""
    redactor = Redactor(known)
    safe = redactor.text(text)
    assert redactor.restore(safe) == text
    assert "@example.invalid" not in safe
    if "value21" in text:
        assert "value21 0.21" in safe
