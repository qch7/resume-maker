"""共享内容摘要和基础凭据遮盖"""

import hashlib
import re

SECRET_VALUE = re.compile(
    r"(?im)([\"']?(?:api[_-]?key|access[_-]?token|secret|password|passwd|authorization)"
    r"[\"']?\s*[:=]\s*)([^\r\n,]+)"
)


def digest(data: bytes) -> str:
    """计算 SHA-256 摘要，用于输入指纹、文件完整性及导出追溯"""
    return hashlib.sha256(data).hexdigest()


def redact(text: str) -> str:
    """遮盖明显的口令和 API 密钥，降低快照和错误日志泄露敏感值的风险"""
    text = SECRET_VALUE.sub(r"\1<redacted>", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "<redacted>", text)
