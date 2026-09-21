"""真实证书验收中发现的字段标签和 OCR 排版变体回归"""

import pytest

from resume_maker.integrations.privacy import TOKEN, Redactor


@pytest.mark.parametrize(
    ("label", "identity"),
    [
        ("颁发单位", "合成证书委员会"),
        ("学校", "合成测试大学"),
        ("证书编号", "CERT-SYNTHETIC-4726"),
        ("姓名", "林沐晴"),
        ("Recipient", "Synthetic Person"),
        ("Issued by", "Synthetic Committee"),
    ],
)
@pytest.mark.parametrize("separator", ["：", "\n", ":\n"])
def test_certificate_identity_labels_are_discovered(label, identity, separator):
    """未保存过的证书身份字段在同行或下一行均先脱敏"""
    raw = label + separator + identity
    redactor = Redactor()
    safe = redactor.prompt(raw)
    assert identity not in safe
    assert TOKEN.search(safe)
    assert redactor.restore(safe) == raw


@pytest.mark.parametrize(
    ("known", "variant"),
    [
        ("林沐晴", "林 沐 晴"),
        ("林沐晴", "林\u200b沐晴"),
        ("13900004726", "１３９００００４７２６"),
        ("13900004726", "139 0000 4726"),
        ("CERT-4726", "ＣＥＲＴ－４７２６"),
        ("星桥测试大学", "星桥\n测试大学"),
    ],
)
def test_known_identity_ocr_spacing_and_width_are_masked(known, variant):
    """OCR 插入空白、不可见字符和全角字符不绕过已登记身份"""
    raw = "材料正文 " + variant
    redactor = Redactor([known])
    safe = redactor.prompt(raw)
    assert variant not in safe
    assert TOKEN.search(safe)
    assert safe.count("\n") == raw.count("\n")
    assert redactor.restore(safe) == raw


@pytest.mark.parametrize(
    "raw",
    ["１３９００００４７２６", "ｐｅｒｓｏｎ＠ｅｘａｍｐｌｅ．ｉｎｖａｌｉｄ", "139\u200b00004726"],
)
def test_unknown_contact_width_and_format_controls(raw):
    """首次出现的电话和邮箱也识别全角字符及不可见格式符"""
    redactor = Redactor()
    safe = redactor.prompt(raw)
    assert raw not in safe and TOKEN.search(safe)
    assert redactor.restore(safe) == raw
