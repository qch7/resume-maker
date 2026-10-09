"""CLI 连接的有限重试参数决定本地替身的实际请求次数"""

import httpx
import pytest

from resume_maker.domain.models import ProviderSettings
from resume_maker.plugin_packages.ext_provider_codex.integrations.providers.connection import (
    connection,
)


@pytest.mark.parametrize("retries", [0, 1, 2])
def test_inherited_retry_budget_controls_attempt_count(tmp_path, retries):
    """使用隔离配置和本地传输模拟连续失败，确保请求次数遵守原预算"""
    (tmp_path / "config.toml").write_text(
        'model="synthetic"\nmodel_provider="test"\n[model_providers.test]\n'
        'name="test"\nbase_url="https://example.invalid/v1"\n'
        f"request_max_retries={retries}\nstream_max_retries=0\nstream_idle_timeout_ms=1000\n",
    )
    values, _ = connection(ProviderSettings(), {"CODEX_HOME": str(tmp_path), "OPENAI_API_KEY": ""})
    attempts = []

    def failure(request):
        """所有请求都在内存中失败，不触及真实供应商"""
        attempts.append(request)
        return httpx.Response(503)

    provider = values["model_providers"]["resume-provider"]
    with httpx.Client(transport=httpx.MockTransport(failure)) as client:
        for _ in range(1 + provider.get("request_max_retries", 4)):
            if client.post(provider["base_url"] + "/responses").is_success:
                break
    assert len(attempts) == 1 + retries
