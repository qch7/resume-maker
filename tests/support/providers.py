"""合成资料使用的 Provider 契约替身"""

from resume_maker.domain.models import AIResult


def read_test_document(*args):
    """图片测试按需加载真实本机 OCR，测试可替换解码结果"""
    from resume_maker.plugin_packages.provider_rapidocr.local_ocr import read_document

    return read_document(*args)


def read_test_page(*args):
    """整页测试通过真实图片隐私处理器保护合成资料"""
    from resume_maker.integrations.providers.page_images import read_document

    return read_document(*args)


def privacy_provider(*, runner=None, environment=None, privacy=None):
    """显式装配真实隐私网关，模型传输由测试替身控制"""
    from resume_maker.integrations.privacy_gateway import PrivacyGateway
    from resume_maker.plugin_packages.ext_provider_codex.integrations.providers.cli import run_cli

    provider = PrivacyGateway(
        runner=runner or run_cli,
        environment=environment,
        privacy=privacy,
        ocr=read_test_document,
        images=True,
    )
    provider.page_ocr = read_test_page
    return provider


class ProviderStub:
    """为合成图像启用本机直读，具体测试负责实现需要的模型响应"""

    supports_images = True
    supports_mosaic_images = False
    supports_page_images = False
    preprocess_images = False

    @property
    def sensitive_values(self) -> set[str]:
        """每次返回独立空集合，测试替身不共享可变隐私数据"""
        return set()

    def with_private_data(self, value):
        """替身只处理合成资料，不建立真实隐私上下文"""
        return self

    def register_ocr(self, document):
        """合成资料无须登记，真实身份登记由隐私出口回归测试覆盖"""

    def read_ocr(self, path, cancelled):
        """测试按公开接口读取当前注入或替换的 OCR 结果"""
        return read_test_document(path, cancelled)

    def run(self, **kwargs):
        """经历请求复用同一结构化替身入口"""
        return self.run_structured(result_model=AIResult, **kwargs)

    def run_structured(self, **kwargs):
        """未配置结果的模型请求立即失败，防止替身意外调用真实供应商"""
        raise AssertionError("测试必须提供结构化模型结果")
