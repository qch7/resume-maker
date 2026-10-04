"""兼容独立调用的 Codex 适配器，应用通过系统隐私服务装配"""

from resume_maker.integrations.privacy_gateway import PrivacyGateway
from resume_maker.integrations.privacy_gateway import schema as schema
from resume_maker.integrations.privacy_gateway import structured_text as structured_text
from resume_maker.integrations.providers.cli import run_cli


def read_document(*args):
    """需要图片处理时才加载本机 OCR 依赖"""
    from resume_maker.integrations.local_ocr import read_document as read

    return read(*args)


def read_page(*args):
    """兼容独立页面处理器的 OCR 注入入口"""
    from resume_maker.integrations.providers.page_images import read_document as read

    return read(*args)


class CodexProvider(PrivacyGateway):
    """保留独立调用入口，隐私实现归系统网关所有"""

    def __init__(self, *, environment=None, privacy=None, runner=None):
        """兼容既有调用方和测试注入的脱敏传输"""
        super().__init__(
            runner=runner or run_cli,
            environment=environment,
            privacy=privacy,
            ocr=read_document,
            images=True,
        )
        self.page_ocr = read_page
