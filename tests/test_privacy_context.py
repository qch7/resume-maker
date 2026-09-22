"""验证业务名称和求职信息可供模型理解，身份字段仍遮盖并在本机还原"""

import json
import re
import threading

import pymupdf
import pytest
from test_privacy import provider_at, reply, run

from resume_maker.domain.honors import HonorRecognition
from resume_maker.domain.models import ProviderSettings
from resume_maker.integrations.privacy import TOKEN, Redactor
from resume_maker.integrations.privacy_store import PrivacyStore


@pytest.mark.parametrize("name", ["大学英语四级", "软件设计师", "数学建模竞赛", "文档解析平台"])
def test_saved_business_names_do_not_pollute_other_requests(catalog, name):
    """保存过的证书名称不会使后续证书或项目材料丢失业务含义"""
    catalog.db.set_setting(
        "honor:synthetic",
        {"fields": {"name": name, "recipient": "林沐晴", "certificate_number": "CERT-4726"}},
    )
    redactor = PrivacyStore(catalog.db).redactor()
    raw = f"{name}\n获奖人：林沐晴\n证书编号：CERT-4726"
    safe = redactor.prompt(raw)
    assert name in safe
    assert "林沐晴" not in safe and "CERT-4726" not in safe
    assert redactor.restore(safe) == raw


def test_personal_context_preserves_qualifications_and_protects_hidden_identity(tmp_path):
    """未保存资料保留专业、职位和成绩，隐藏姓名及学校等信息仍进入统一出口"""
    document = {
        "personal": {
            "name": "林沐晴",
            "job_title": "软件工程师",
            "gpa": "3.85/4.0",
            "location": "合成测试区",
            "hidden_fields": ["name"],
            "custom_fields": [
                {"label": "工作单位", "value": "合成测试单位"},
                {"label": "专业", "value": "计算机科学"},
                {"label": "证书名称", "value": "大学英语四级"},
                {"label": "昵称", "value": "合成私人代号"},
            ],
        },
        "sections": [
            {
                "kind": "education",
                "entries": [{"title": "星桥测试大学", "subtitle": "计算机科学"}],
            }
        ],
        "project": {"name": "文档解析平台"},
    }
    private = ["林沐晴", "合成测试区", "合成测试单位", "星桥测试大学", "合成私人代号"]
    public = ["软件工程师", "3.85/4.0", "计算机科学", "大学英语四级", "文档解析平台"]

    def handle(payload):
        """核对供应商材料后回显占位符，检验本机恢复完整结构"""
        assert all(value not in payload["input"] for value in private)
        assert all(value in payload["input"] for value in public)
        return reply(payload["input"])

    provider = provider_at(tmp_path, handle).with_private_data(document)
    prompt = "整理简历\n" + json.dumps(document, ensure_ascii=False)
    result = run(provider, tmp_path, prompt)
    assert json.loads(result.reply.split("\n", 1)[1]) == document


@pytest.mark.parametrize(
    "text",
    [
        "filename: parser.py",
        "project_name: 文档解析平台",
        "Project name: 文档解析平台",
        "certificate_name: 大学英语四级",
        "证书名称：大学英语四级",
        "项目name: 文档解析平台",
    ],
)
def test_business_labels_are_not_person_name_suffixes(text):
    """文件名和业务名称标签不因含有 name 后缀而被识别为姓名"""
    assert Redactor().prompt(text) == text


@pytest.mark.parametrize(
    "label", ["Name", "Full name", "Person_name", "姓名", "学校", "中文姓名", "证书；Name"]
)
def test_explicit_identity_labels_remain_sensitive(label):
    """明确身份标签继续支持同行、换行及本机还原"""
    raw = f"{label}:\nSynthetic Identity"
    redactor = Redactor()
    safe = redactor.prompt(raw)
    assert "Synthetic Identity" not in safe and TOKEN.search(safe)
    assert redactor.restore(safe) == raw


def test_business_values_can_still_be_explicitly_private():
    """业务字段继续服从补充敏感词和联系方式等格式规则"""
    redactor = Redactor(["大学英语四级"])
    raw = {"name": "大学英语四级", "project": {"name": "person@example.invalid"}}
    safe = json.loads(redactor.prompt(json.dumps(raw, ensure_ascii=False)))
    assert TOKEN.fullmatch(safe["name"])
    assert TOKEN.fullmatch(safe["project"]["name"])
    assert redactor.restore(safe) == raw


def test_saved_certificate_name_survives_pdf_extraction_and_model_roundtrip(tmp_path, catalog):
    """复现已保存四级名称再识别证书的链路，输出名称完整且身份仅在本机还原"""
    catalog.db.set_setting(
        "honor:previous",
        {"fields": {"name": "大学英语四级", "recipient": "林沐晴"}},
    )
    source = tmp_path / "synthetic-certificate.pdf"
    title = "全国大学英语四级考试"
    lines = [title, "姓名：林沐晴", "学校：星桥测试大学", "报告单编号：CET-4726", "成绩：580"]
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "\n".join(lines), fontname="china-s")
        pdf.save(source)

    def handle(payload):
        """只从实际收到的脱敏文字提取名称和占位符，供应商接触不到真实身份"""
        documents = json.loads(payload["input"].split("禁止推测）：\n", 1)[1])
        text = documents[0]["text"]
        assert text.splitlines()[0] == title
        assert "成绩：580" in text
        assert all(
            value not in json.dumps(payload, ensure_ascii=False)
            for value in ["林沐晴", "星桥测试大学", "CET-4726"]
        )
        recipient = re.search(r"姓名：([^\n]+)", text)[1]
        number = re.search(r"报告单编号：([^\n]+)", text)[1]
        assert TOKEN.fullmatch(recipient) and TOKEN.fullmatch(number)
        return {
            "fields": {
                "name": text.splitlines()[0],
                "recipient": recipient,
                "certificate_number": number,
            },
            "text": text,
            "warnings": [],
        }

    provider = provider_at(tmp_path, handle, catalog.db)
    result = provider.run_structured(
        result_model=HonorRecognition,
        workspace=tmp_path / "workspace",
        prompt="识别证书",
        thread_id=None,
        settings=ProviderSettings(),
        cancelled=threading.Event(),
        emit=lambda *_: None,
        images=[source],
    )
    assert result.fields.name == title
    assert result.fields.recipient == "林沐晴"
    assert result.fields.certificate_number == "CET-4726"
    assert all(line in result.text for line in lines)
    audit = catalog.db.setting("privacy_audit")[0]
    assert audit["status"] == "completed"
    assert "林沐晴" not in json.dumps(audit, ensure_ascii=False)
