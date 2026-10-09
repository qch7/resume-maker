"""身份标识的格式变体、完整遮盖和正常数字保留"""

import json
import threading

import pytest

from resume_maker.domain.honors import HonorRecognition
from resume_maker.domain.models import ProviderSettings
from resume_maker.integrations.privacy import TOKEN, Redactor
from tests.support.providers import privacy_provider


@pytest.mark.parametrize(
    "number", ["7628102190437", "762810219043785", "762810219043785610", "76281021904378561082735"]
)
def test_entire_identifier_wins_over_short_private_term(number):
    """短敏感词命中编号内部时，仍必须遮住完整编号并准确还原"""
    redactor = Redactor(["21"])
    safe = redactor.prompt(number)
    assert TOKEN.fullmatch(safe)
    assert redactor.restore(safe) == number


@pytest.mark.parametrize(
    "value",
    [
        "７６２８１０２１９０４３７８５",
        "762810\u200b219043785",
        "76281-02190-43785",
        "762810 2190 43785",
        "76281\n02190\n43785",
        "76281\r\n02190\r\n43785",
        "76281／02190／43785",
        "76281－02190－43785",
    ],
)
def test_formatted_identifiers_hide_every_component(value):
    """字宽、控制符、分组和换行不会留下能拼回编号的片段"""
    redactor = Redactor(["21"])
    safe = redactor.prompt(value)
    assert not any(character.isdecimal() for character in TOKEN.sub("", safe))
    assert redactor.restore(safe) == value
    assert safe.count("\n") == value.count("\n")


@pytest.mark.parametrize(
    "label,number",
    [
        ("准考证号", "A-762810"),
        ("报告单编号", "XZ-73841"),
        ("准 考 证 号", "87329"),
        ("验证码", "AB2C D4EF GH6J K8LM"),
        ("student ID", "ST-7843"),
    ],
)
def test_labeled_identifiers_are_fully_masked(label, number):
    """有明确标签的短编号及字母数字编码也需完整替换"""
    redactor = Redactor()
    safe = redactor.prompt(f"{label}：{number}")
    assert TOKEN.fullmatch(safe.split("：", 1)[1])
    assert redactor.restore(safe) == f"{label}：{number}"


def test_grouped_verification_code_needs_no_saved_identity():
    """没有标签的证书分组校验串也整体遮盖"""
    redactor = Redactor()
    value = "AB2C D4EF GH6J K8LM"
    assert TOKEN.fullmatch(redactor.prompt(value))
    assert redactor.restore(redactor.text(value)) == value


def test_short_numeric_terms_keep_unrelated_dates_scores_and_code():
    """年龄等短数字只匹配独立值，不改坏日期、成绩和程序符号"""
    redactor = Redactor(["21", "20", "1"])
    ordinary = "2024年12月；总分575；听力206；阅读201；翻译168\nreturn value21 + 0.21"
    assert redactor.prompt(ordinary) == ordinary
    assert TOKEN.search(redactor.prompt("年龄：21岁"))
    token = redactor.text("21")
    assert redactor.text(token) == token


def test_grouped_scores_and_dates_are_preserved():
    """分组成绩、年月日、年份列表和结构坐标不应被合并当成身份编号"""
    redactor = Redactor()
    text = "575 206 201 168\n2024-12-01\n2024 2025 2026 2027\n0.1234567890123"
    assert redactor.prompt(text) == text
    value = {"box": [0.1234567890123, 0.5, 0.75, 0.9], "confidence": 0.9358}
    assert redactor.protect(value) == value
    number = "762810219043785"
    safe = redactor.prompt(number + ".")
    assert TOKEN.fullmatch(safe[:-1]) and safe.endswith(".")


def test_overlapping_known_value_cannot_expose_identifier_suffix():
    """已知值跨过编号开头时，合并遮盖范围并保留精确引文"""
    value = "owner 762810219043785"
    redactor = Redactor(["owner 7628"])
    safe = redactor.prompt(value)
    assert TOKEN.fullmatch(safe)
    assert redactor.restore(safe) == value


def test_ocr_fragments_and_structured_aliases_use_the_same_gateway(tmp_path, monkeypatch):
    """OCR 分块、汇总文字和结构化编号全部遮盖，模型结果在本机完整还原"""
    number = "762810219043785"
    fragments = ["76281", "02190", "43785"]
    document = {
        "text": "\n".join(fragments),
        "pages": [{"blocks": [{"text": value, "confidence": 1.0} for value in fragments]}],
    }
    monkeypatch.setattr(
        "resume_maker.plugin_packages.provider_rapidocr.local_ocr.read_document",
        lambda *_: document,
    )

    def runner(payload, *_):
        """模型只回显收到的占位符以验证完整的本机字段恢复"""
        context = json.loads(payload["input"].split("\n本地 OCR")[0].splitlines()[-1])
        ocr = json.loads(payload["input"].split("禁止推测）：\n")[1])[0]
        assert TOKEN.fullmatch(context["report_number"])
        assert TOKEN.fullmatch(context["student_id"])
        assert TOKEN.fullmatch(context["source_identifier"])
        assert all(TOKEN.fullmatch(row["text"]) for row in ocr["pages"][0]["blocks"])
        assert not any(part in json.dumps(payload) for part in fragments)
        return json.dumps(
            {
                "fields": {"name": "合成考试", "certificate_number": context["report_number"]},
                "text": ocr["text"],
                "warnings": [],
            }
        )

    result = privacy_provider(runner=runner).run_structured(
        result_model=HonorRecognition,
        workspace=tmp_path,
        thread_id=None,
        prompt="核对\n"
        + json.dumps(
            {"report_number": number, "student_id": "ST-7843", "source_identifier": number}
        ),
        settings=ProviderSettings(),
        cancelled=threading.Event(),
        emit=lambda *_: None,
        images=[tmp_path / "synthetic.pdf"],
    )
    assert result.fields.certificate_number == number
    assert result.text == document["text"]


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
