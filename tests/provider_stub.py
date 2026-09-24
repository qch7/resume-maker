"""合成资料测试使用的显式 Provider 契约，不加载真实凭据或隐私库"""

from resume_maker.domain.models import AIResult


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

    def run(self, **kwargs):
        """经历请求复用同一结构化替身入口"""
        return self.run_structured(result_model=AIResult, **kwargs)

    def run_structured(self, **kwargs):
        """未配置结果的模型请求立即失败，防止替身意外调用真实供应商"""
        raise AssertionError("测试必须提供结构化模型结果")
