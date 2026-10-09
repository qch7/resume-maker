"""公开 OCR 契约对第三方结果、空结果及取消的验收"""

import threading
from copy import deepcopy
from pathlib import Path

import pytest

from resume_maker.integrations import document_limits, privacy_policy
from resume_maker.sdk import ocr
from resume_maker.sdk.model import Cancelled, ProviderError
from resume_maker.sdk.ocr import (
    OCR_MAX_PAGES,
    OCR_REVIEW_CONFIDENCE,
    ValidatedOCR,
    validate_ocr_document,
)


def document():
    """合成一页文字结果，不含真实图片或个人资料"""
    return {
        "pages": [
            {
                "width": 100,
                "height": 200,
                "method": "synthetic",
                "blocks": [{"text": "合成文字", "box": [0.1, 0.1, 0.9, 0.2], "confidence": 0.95}],
            }
        ],
        "text": "合成文字",
        "seconds": 0.01,
        "needs_review": False,
        "notice": "合成验收",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["pages"][0]["blocks"][0].update(box=[0, 0, 2, 1]),
        lambda value: value["pages"][0]["blocks"][0].update(box=[0.5, 0.1, 0.4, 0.2]),
        lambda value: value["pages"][0]["blocks"][0].update(confidence=float("nan")),
        lambda value: value["pages"][0]["blocks"][0].update(confidence=True),
        lambda value: value["pages"][0]["blocks"][0].update(confidence=0.5),
        lambda value: value.update(text="错误汇总"),
        lambda value: value.update(seconds=float("inf")),
        lambda value: value.update(pages=[deepcopy(value["pages"][0])] * (OCR_MAX_PAGES + 1)),
    ],
)
def test_invalid_provider_results_are_rejected(mutate):
    """非法结果在业务消费者之前被拒绝，错误信息不包含原文"""
    value = document()
    mutate(value)
    with pytest.raises(ProviderError) as error:
        validate_ocr_document(value)
    assert "合成文字" not in str(error.value)


def test_public_limits_match_consumers_and_empty_pages_remain_valid():
    """空页可以保留原分页，但整份空文档明确报告无法识别"""
    for name in ("OCR_MAX_PAGES", "OCR_MAX_BLOCKS", "OCR_MAX_FILE_BYTES", "OCR_MAX_TEXT_CHARS"):
        assert getattr(document_limits, name) == getattr(ocr, name)
    assert privacy_policy.OCR_REVIEW_CONFIDENCE == OCR_REVIEW_CONFIDENCE
    value = document()
    value["pages"].append({"width": 100, "height": 200, "method": "empty", "blocks": []})
    value["text"] += "\n\n"
    assert validate_ocr_document(value) is value
    value["pages"][0]["blocks"] = []
    value["text"] = "\n\n"
    with pytest.raises(ProviderError, match="未识别"):
        validate_ocr_document(value)


def test_cancelled_result_is_never_published():
    """提供方忽略执行中取消时，能力入口仍拒绝迟到的结果"""
    calls = []
    cancelled = threading.Event()

    class Backend:
        """合成提供方模拟请求完成时收到停用信号"""

        def read_document(self, path, signal):
            """返回前发出取消，验证宿主的结果发布边界"""
            calls.append(path)
            signal.set()
            return document()

    service = ValidatedOCR(Backend())
    with pytest.raises(Cancelled):
        service.read_document(Path("synthetic.png"), cancelled)
    with pytest.raises(Cancelled):
        service.read_document(Path("another.png"), cancelled)
    assert calls == [Path("synthetic.png")]
