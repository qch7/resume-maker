"""本地 OCR的注册和生命周期入口"""

from resume_maker.plugins.support import dependency, publish
from resume_maker.sdk.ocr import ValidatedOCR


def activate(context):
    """发布当前选择的 OCR 提供方"""
    publish(context, "ocr", ValidatedOCR(dependency(context, "ocr.backend")), observed=False)
