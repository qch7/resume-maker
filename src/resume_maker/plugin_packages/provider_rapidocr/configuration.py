"""RapidOCR 的本机推理策略，模型来源和隐私保护规则固定由代码管理"""

from pydantic import Field

from resume_maker.sdk.configuration import PluginSettings


class Settings(PluginSettings):
    """每个插件实例持有独立模型，重配置先等待当前识别结束"""

    intra_op_num_threads: int = Field(default=2, ge=1, le=16, description="算子内部 CPU 线程数")
    inter_op_num_threads: int = Field(default=1, ge=1, le=16, description="算子之间 CPU 线程数")
    detection_side: int = Field(default=736, ge=128, le=4096, description="文本检测最长边像素数")
    base_side: int = Field(default=960, ge=128, le=2048, description="首次识别最长边像素数")
    retry_side: int = Field(default=2000, ge=256, le=4096, description="复核识别最长边像素数")
    text_score: float = Field(default=0.3, ge=0, le=1, description="引擎输出文字的最低置信度")
    adaptive_retry_enabled: bool = Field(default=True, description="空白、稀疏或小字页复核一次")
    small_text_height: float = Field(default=14, ge=0, le=64, description="小字复核高度阈值像素数")
    sparse_result_count: int = Field(default=2, ge=0, le=20, description="稀疏文字复核行数阈值")
    pdf_render_side: int = Field(
        default=2400, ge=512, le=4096, description="PDF 栅格化最长边像素数"
    )
    pdf_render_scale: float = Field(default=3, ge=1, le=4, description="PDF 栅格化最大倍率")
