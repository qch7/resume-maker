"""临时 CLI home 只接收鉴权文件，刷新后在原凭据未变化时保存新状态"""

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from resume_maker.integrations.providers.base import Cancelled, ProviderError

LOCK = threading.Lock()


@contextmanager
def credential_lock(cancelled):
    """等待刷新锁时继续响应取消，避免排队请求阻塞终止"""
    while not LOCK.acquire(timeout=0.1):
        if cancelled.is_set():
            raise Cancelled("请求已取消。")
    try:
        if cancelled.is_set():
            raise Cancelled("请求已取消。")
        yield
    finally:
        LOCK.release()


@contextmanager
def isolated_credentials(root, env, cancelled):
    """串行复用登录凭据，避免并发临时副本重复刷新同一登录令牌"""
    source = Path(env["CODEX_HOME"]) / "auth.json"
    home = root / "control/codex-home"
    home.mkdir(mode=0o700)
    target = home / "auth.json"
    with credential_lock(cancelled):
        original = source.read_bytes() if source.is_file() else None
        if original is not None:
            if len(original) > 128 * 1024:
                raise ProviderError("CLI 鉴权文件超过大小限制。")
            value = json.loads(original)
            if not isinstance(value, dict):
                raise ProviderError("CLI 鉴权文件格式无效。")
            target.write_bytes(original)
        try:
            yield {**env, "CODEX_HOME": str(home)}
        finally:
            if original is not None and target.is_file():
                refreshed = target.read_bytes()
                if refreshed != original and source.read_bytes() == original:
                    value = json.loads(refreshed)
                    if len(refreshed) > 128 * 1024 or not isinstance(value, dict):
                        raise ProviderError("CLI 刷新后的鉴权文件格式无效，请重新登录。")
                    descriptor, name = tempfile.mkstemp(prefix=".resume-auth-", dir=source.parent)
                    try:
                        with os.fdopen(descriptor, "wb") as output:
                            output.write(refreshed)
                        # 再次核对来源，避免覆盖其他 CLI 已经刷新的文件
                        if source.read_bytes() == original:
                            os.replace(name, source)
                    finally:
                        Path(name).unlink(missing_ok=True)
