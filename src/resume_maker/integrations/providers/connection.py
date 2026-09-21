"""只读取 CLI 连接配置中的供应商字段，不加载插件、工具、记忆或会话"""

import json
import os
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from resume_maker.integrations.providers.base import ProviderError


def connection(settings, environment):
    """解析 API 凭据和 Responses 地址，订阅鉴权及未知协议明确拦截"""
    env = {**os.environ, **environment}
    home = Path(env.get("CODEX_HOME", str(Path.home() / ".codex")))
    try:
        config = (
            tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
            if (home / "config.toml").exists()
            else {}
        )
        if settings.profile:
            if not re.fullmatch(r"[\w-]+", settings.profile):
                raise ProviderError("配置档名称只支持字母、数字、下划线和连字符。")
            profile = home / f"{settings.profile}.config.toml"
            overlay = (
                tomllib.loads(profile.read_text(encoding="utf-8"))
                if profile.exists()
                else config.get("profiles", {}).get(settings.profile)
            )
            if overlay is None:
                raise ProviderError("找不到指定的 CLI 配置档。")
            config = {
                **config,
                **overlay,
                "model_providers": {
                    **config.get("model_providers", {}),
                    **overlay.get("model_providers", {}),
                },
            }
        provider_id = config.get("model_provider", "openai")
        provider = config.get("model_providers", {}).get(provider_id, {})
        if provider_id != "openai" and not provider:
            raise ProviderError("找不到配置的模型供应商。")
        if provider.get("wire_api", "responses") != "responses":
            raise ProviderError("隐私保护目前支持 Responses API，请检查供应商协议。")
        base = provider.get("base_url", "https://api.openai.com/v1")
        parsed = urlsplit(base)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ProviderError(
                "供应商地址必须使用 HTTPS，本机服务可使用 HTTP，地址不能包含凭据或查询参数。"
            )
        key = env.get(provider.get("env_key", "OPENAI_API_KEY"), "")
        key = key or provider.get("experimental_bearer_token", "")
        if not key and not provider.get("env_key") and (home / "auth.json").exists():
            key = json.loads((home / "auth.json").read_text(encoding="utf-8")).get(
                "OPENAI_API_KEY", ""
            )
        model = settings.model or config.get("model", "")
        effort = settings.reasoning_effort or config.get("model_reasoning_effort", "")
        if effort not in {"", "minimal", "low", "medium", "high", "xhigh"}:
            raise ProviderError("配置中的思考强度不受支持，请在模型设置中指定有效值。")
        if not key:
            raise ProviderError(
                "隐私保护需要供应商 API 密钥。仅订阅登录暂不支持；请在 CLI 配置中设置 API 凭据。"
            )
        if not model:
            raise ProviderError("请在模型设置或 CLI 配置中指定模型名称。")
        if not isinstance(key, str) or "\n" in key or "\r" in key:
            raise ProviderError("供应商 API 凭据格式无效。")
        return base.rstrip("/") + "/responses", key, model, effort
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ProviderError("无法读取供应商连接配置，请检查本机 CLI 配置和 API 凭据。") from exc
