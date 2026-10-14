"""归一化视图保留逐字符语义、原文坐标及请求内阶段隔离"""

import random
import unicodedata
from array import array

import pytest

from resume_maker.integrations import privacy, privacy_identifiers, privacy_text
from resume_maker.integrations.privacy import Redactor
from resume_maker.integrations.privacy_text import compact_text, normalized_text


@pytest.mark.parametrize("compact", [False, True])
def test_normalized_views_preserve_per_character_reference(compact):
    """展开、组合字符、控制符及各类空白的坐标同逐字符定义完全一致"""
    randomizer = random.Random(49)
    alphabet = "abc 12\t\r\n\x1c\u200b\u200d\ufeffＡ１㍿ﬃ\u0301\u00a0\u3000\u2028"
    cases = ["", "e\u0301", "ﬃ\u200bＡ\u00a0１", "\x1c\t\r\n ", "普通正文"]
    cases.extend("".join(randomizer.choices(alphabet, k=200)) for _ in range(100))
    for value in cases:
        expected = [
            (normalized, index)
            for index, character in enumerate(value)
            if unicodedata.category(character) != "Cf"
            for normalized in unicodedata.normalize("NFKC", character)
            if not compact or not normalized.isspace()
        ]
        text, positions = normalized_text(value, compact=compact)
        assert text == "".join(character for character, _ in expected)
        assert list(positions) == [index for _, index in expected]


def test_ascii_identity_uses_constant_size_positions_and_compact_mapping():
    """普通源码复用原字符串，去空白后才分配紧凑整数坐标"""
    value = "const ordinary = count + 1;\n" * 20000
    view = normalized_text(value)
    assert view[0] is value
    assert isinstance(view[1], range)
    assert view[1][-1] == len(value) - 1
    text, positions = compact_text(view)
    assert text == "constordinary=count+1;" * 20000
    assert isinstance(positions, array)
    assert positions.itemsize == 4
    assert all(
        value[position] == character for character, position in zip(text, positions, strict=True)
    )


def test_detectors_share_views_and_rebuild_after_credentials_change(monkeypatch):
    """全文每阶段只归一化一次，凭据移除改变长度后不能沿用旧坐标"""
    original, calls = normalized_text, []
    raw = "password: synthetic-secret\n" + (
        "contact ｐｅｒｓｏｎ＠ｅｘａｍｐｌｅ．ｉｎｖａｌｉｄ\n普通正文"
    )
    cleaned = raw.replace("synthetic-secret", "[凭据已移除]")

    def counted(value, **kwargs):
        """只计全文视图，固定敏感词及局部编号仍可独立处理"""
        if value in (raw, cleaned):
            calls.append(value)
        return original(value, **kwargs)

    for module in (privacy, privacy_text, privacy_identifiers):
        monkeypatch.setattr(module, "normalized_text", counted)
    redactor = Redactor(["SyntheticPrivate"])
    redactor.learn(raw)
    safe = redactor.text(raw)
    assert calls == [raw, cleaned]
    assert "synthetic-secret" not in safe
    assert "ｐｅｒｓｏｎ" not in safe
    assert redactor.restore(safe) == cleaned


def test_shared_unicode_views_restore_expansion_and_cross_line_identity():
    """兼容展开、多行空白及格式控制符仍按原文片段还原"""
    raw = "联系：ｏﬃｃｅ＠ｅｘａｍｐｌｅ．ｉｎｖａｌｉｄ；星\u200b桥\r\n测 试 大 学"
    redactor = Redactor(["星桥测试大学"])
    redactor.learn(raw)
    safe = redactor.text(raw)
    assert "ｏﬃｃｅ" not in safe and "测 试 大 学" not in safe
    assert safe.count("\r\n") == 1
    assert redactor.restore(safe) == raw
    assert Redactor().prefix != redactor.prefix
