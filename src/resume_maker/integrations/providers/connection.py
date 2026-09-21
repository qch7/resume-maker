"""只复用 CLI 的模型、供应商和鉴权，不继承工具及项目配置"""

import os
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from resume_maker.integrations.providers.base import ProviderError


def connection(settings, environment):
    """从现有配置选取连接字段，订阅登录仍由 CLI 自己处理"""
    original = {**os.environ, **environment}
    home = Path(original.get("CODEX_HOME", str(Path.home() / ".codex")))
    try:
        file = home / "config.toml"
        config = tomllib.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
        if settings.profile:
            if not re.fullmatch(r"[\w-]+", settings.profile):
                raise ProviderError("配置档名称只支持字母、数字、下划线和连字符。")
            file = home / f"{settings.profile}.config.toml"
            overlay = (
                tomllib.loads(file.read_text(encoding="utf-8"))
                if file.exists()
                else config.get("profiles", {}).get(settings.profile)
            )
            if not isinstance(overlay, dict):
                raise ProviderError("找不到指定的 CLI 配置档。")
            config = {
                **config,
                **overlay,
                "model_providers": {
                    **config.get("model_providers", {}),
                    **overlay.get("model_providers", {}),
                },
            }
        # 父进程保留鉴权所需的系统环境，工具子进程使用独立的空环境白名单
        allowed = {
            "systemroot",
            "windir",
            "systemdrive",
            "comspec",
            "home",
            "userprofile",
            "appdata",
            "localappdata",
            "programdata",
            "programfiles",
            "programfiles(x86)",
            "temp",
            "tmp",
            "path",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
            "ssl_cert_file",
            "ssl_cert_dir",
        }
        env = {k: v for k, v in original.items() if k.lower() in allowed}
        env["CODEX_HOME"] = str(home.resolve())
        values = {}
        model = settings.model or config.get("model", "")
        effort = settings.reasoning_effort or config.get("model_reasoning_effort", "")
        if model:
            values["model"] = model
        if effort:
            if effort not in {"minimal", "low", "medium", "high", "xhigh"}:
                raise ProviderError("配置中的思考强度不受支持。")
            values["model_reasoning_effort"] = effort
        provider_id = config.get("model_provider", "openai")
        provider = config.get("model_providers", {}).get(provider_id, {})
        if provider_id != "openai" and not provider:
            raise ProviderError("找不到配置的模型供应商。")
        if provider:
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
                    parsed.scheme == "http"
                    and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                )
            ):
                raise ProviderError("远程供应商必须使用 HTTPS，地址不能包含凭据或查询参数。")
            selected = {
                k: provider[k]
                for k in ("name", "base_url", "wire_api", "requires_openai_auth")
                if k in provider
            }
            selected.setdefault("name", "Resume Maker provider")
            key = original.get(provider.get("env_key", "OPENAI_API_KEY"), "") or provider.get(
                "experimental_bearer_token", ""
            )
            if key:
                env["RESUME_MAKER_PROVIDER_KEY"] = key
                selected["env_key"] = "RESUME_MAKER_PROVIDER_KEY"
            elif provider.get("env_key"):
                raise ProviderError("供应商配置指定的 API 环境变量为空。")
            values.update(
                model_provider="resume-provider", model_providers={"resume-provider": selected}
            )
        elif original.get("OPENAI_API_KEY"):
            env["OPENAI_API_KEY"] = original["OPENAI_API_KEY"]
        if config.get("cli_auth_credentials_store") in {"auto", "file", "keyring"}:
            values["cli_auth_credentials_store"] = config["cli_auth_credentials_store"]
        return values, env
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ProviderError("无法读取 CLI 连接配置，请检查供应商设置。") from exc
