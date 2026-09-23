"""固定模型工具元数据，避免内置模型目录重新启用代码执行或编辑能力"""

import json

from resume_maker.integrations.providers.base import ProviderError


def write_catalog(root, settings, *, images=False):
    """保留选定模型名称，通过受控目录固定标准工具协议和只读能力"""
    model = settings.get("model")
    if not model:
        raise ProviderError("隐私工具模式需要明确的模型名称，请在模型设置或 CLI 配置中填写。")
    entry = {
        "slug": model,
        "display_name": model,
        "description": "Resume Maker text analysis",
        "supported_reasoning_levels": [],
        "shell_type": "disabled",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 0,
        "upgrade": None,
        "model_messages": {
            "instructions_template": (
                "你负责分析脱敏后的简历材料。仅使用 resume_materials 服务的只读材料工具，"
                "禁止调用 CLI 内置的 MCP 资源发现和读取工具。"
                "保留隐私占位符和准确引文，按指定 JSON 契约返回结果。"
            )
        },
        "default_reasoning_summary": "none",
        "support_verbosity": False,
        "apply_patch_tool_type": None,
        "truncation_policy": {"mode": "bytes", "limit": 30000},
        "effective_context_window_percent": 95,
        "experimental_supported_tools": [],
        "input_modalities": ["text", "image"] if images else ["text"],
        "include_skills_usage_instructions": False,
        "include_plugin_usage_instructions": False,
        "include_apps_usage_instructions": False,
        "supports_search_tool": False,
        "supports_experimental_context": False,
        "use_responses_lite": False,
        "node_repl_disabled": True,
        "tool_mode": "direct",
    }
    path = root / "control/model-catalog.json"
    path.write_text(json.dumps({"models": [entry]}, ensure_ascii=False), encoding="utf-8")
    return str(path)
