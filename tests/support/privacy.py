"""隐私出口的合成响应、图片和可控执行器"""

import json
import threading
from io import BytesIO

from PIL import Image, ImageDraw, PngImagePlugin

from resume_maker.domain.models import ProviderSettings
from resume_maker.integrations.privacy_store import PrivacyStore
from tests.support.providers import privacy_provider


def reply(text="完成"):
    """构造不含额外行为的合成模型结果"""
    return {"reply": text, "experience": None, "changes": [], "questions": []}


def provider_at(tmp_path, handler, db=None, *, source_handler=None):
    """注入只接收安全材料的 CLI 替身，不访问用户配置或真实模型"""

    def runner(payload, settings, environment, cancelled, emit, *, source_access=None):
        """回显可控的结构化结果以检查本机还原"""
        result = source_handler(payload, source_access) if source_handler else handler(payload)
        return json.dumps(result, ensure_ascii=False)

    return privacy_provider(privacy=PrivacyStore(db), runner=runner)


def run(provider, tmp_path, prompt, **options):
    """调用真实隐私出口并使用可控的取消信号"""
    return provider.run(
        workspace=tmp_path / "private-workspace",
        prompt=prompt,
        thread_id="old-private-session",
        settings=ProviderSettings(),
        cancelled=options.pop("cancelled", threading.Event()),
        emit=lambda *_: None,
        **options,
    )


def synthetic_image():
    """生成含细小身份文字和元数据的合成人像，不读取任何真实照片"""
    image = Image.new("RGB", (240, 320), "#d8edf6")
    draw = ImageDraw.Draw(image)
    draw.ellipse((65, 25, 175, 185), fill="#e8b997")
    draw.ellipse((65, 15, 175, 70), fill="#303030")
    draw.rectangle((50, 190, 190, 320), fill="#284568")
    draw.text((80, 100), "PRIVATE-ID", fill="black")
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private", "ORIGINAL-METADATA-CANARY")
    output = BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()
