"""只输出合成文字的提供方示例，用于替换及凭据界面验收"""

import threading
from pathlib import Path

from resume_maker.sdk.context import Context, ServiceKey
from resume_maker.sdk.model import Cancelled
from resume_maker.sdk.ocr import OCRBackend, OCRDocument, validate_ocr_document


class SyntheticOCR:
    """本示例不识别原图，也不连接供应商"""

    def read_document(self, path: Path, cancelled: threading.Event) -> OCRDocument:
        """合成结果遵循公开结构，预先取消时不返回文字"""
        if cancelled.is_set():
            raise Cancelled("合成 OCR 已取消。")
        return validate_ocr_document(
            {
                "pages": [
                    {
                        "width": 100,
                        "height": 100,
                        "method": "synthetic",
                        "blocks": [
                            {"text": "合成验收文字", "box": [0.1, 0.1, 0.8, 0.2], "confidence": 1.0}
                        ],
                    }
                ],
                "text": "合成验收文字",
                "seconds": 0.0,
                "needs_review": False,
                "notice": "仅供合成验收，不代表实际识别结果。",
            }
        )

    def close(self) -> None:
        """示例没有后台执行及需要回收的资源"""
        pass


def activate(context: Context):
    """注册唯一 OCR 提供方，凭据配置仅用于展示引用控件"""
    backend = SyntheticOCR()
    context.provide(ServiceKey[OCRBackend]("ocr.backend"), backend)
    context.effect(backend.close)
