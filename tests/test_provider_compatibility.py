"""验证开放模型参数和配置档名称，同时保持文件读取及配置继承边界"""

import json

import pytest
from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.domain.models import ProviderSettings
from resume_maker.integrations.providers.base import ProviderError
from resume_maker.integrations.providers.connection import connection
from resume_maker.integrations.providers.model_catalog import write_catalog


def test_custom_efforts_persist_and_inherit_per_function(tmp_path):
    """自定义强度可保存并在重开后使用，空白覆盖继承默认且 none 保持显式值"""
    config = Config(data_dir=tmp_path / "data", token="synthetic")
    with TestClient(create_app(config), headers={"x-resume-token": "synthetic"}) as client:
        for effort in ("none", "max", "ultra", "future-2027", "custom_effort"):
            response = client.put(
                "/api/settings/provider",
                json={
                    "reasoning_effort": " high ",
                    "functions": {
                        "conversation": {"reasoning_effort": f" {effort} "},
                        "project_analysis": {"reasoning_effort": " "},
                    },
                },
            )
            assert response.status_code == 200
            settings = ProviderSettings.model_validate(response.json())
            assert settings.for_function("conversation").reasoning_effort == effort
            assert settings.for_function("project_analysis").reasoning_effort == "high"
    with TestClient(create_app(config), headers={"x-resume-token": "synthetic"}) as client:
        saved = ProviderSettings.model_validate(client.get("/api/settings").json()["provider"])
        assert saved.for_function("conversation").reasoning_effort == "custom_effort"


@pytest.mark.parametrize("effort", ["none", "max", "ultra", "custom_effort"])
@pytest.mark.parametrize("location", ["root", "inline", "file"])
def test_effort_inherits_from_each_cli_configuration(tmp_path, effort, location):
    """主配置和两种 Profile 中的强度经同一校验透传给 CLI，设置仍可覆盖"""
    profile = "团队 profile.v2"
    selection = f'model="provider/model.v2"\nmodel_reasoning_effort=" {effort} "\n'
    config = selection if location == "root" else 'model="base"\n'
    if location == "inline":
        config += f"[profiles.{json.dumps(profile, ensure_ascii=False)}]\n" + selection
    elif location == "file":
        (tmp_path / f"{profile}.config.toml").write_text(selection, encoding="utf-8")
    (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    settings = ProviderSettings(profile="" if location == "root" else profile)
    env = {"CODEX_HOME": str(tmp_path), "OPENAI_API_KEY": ""}
    values, _ = connection(settings, env)
    assert values["model"] == "provider/model.v2"
    assert values["model_reasoning_effort"] == effort
    overridden, _ = connection(settings.model_copy(update={"reasoning_effort": "none"}), env)
    assert overridden["model_reasoning_effort"] == "none"


@pytest.mark.parametrize("name", ["team v2", "team.v2", "中文配置", "team/prod", "../outside"])
def test_inline_profiles_use_literal_names_without_reading_paths(tmp_path, name):
    """内嵌配置使用完整 TOML 键，含路径分隔符的名称也不能转为文件访问"""
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "outside.config.toml").write_text('model="outside-canary"', encoding="utf-8")
    (home / "config.toml").write_text(
        f'[profiles.{json.dumps(name, ensure_ascii=False)}]\nmodel="selected-model"\n',
        encoding="utf-8",
    )
    values, _ = connection(ProviderSettings(profile=name), {"CODEX_HOME": str(home)})
    assert values["model"] == "selected-model"


@pytest.mark.parametrize("name", ["../outside", r"..\outside", "../outside:stream"])
def test_missing_profile_never_reads_outside_cli_home(tmp_path, name):
    """独立配置档不能通过相对路径或 Windows 流名称读取 CLI home 之外的文件"""
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "outside.config.toml").write_text('model="outside-canary"', encoding="utf-8")
    with pytest.raises(ProviderError, match="找不到指定"):
        connection(ProviderSettings(profile=name), {"CODEX_HOME": str(home)})


def test_named_file_keeps_precedence_over_inline_profile(tmp_path):
    """独立配置仍覆盖同名内嵌配置，保留既有的 Profile 选择行为"""
    (tmp_path / "config.toml").write_text(
        '[profiles."team.v2"]\nmodel="inline-model"\n', encoding="utf-8"
    )
    (tmp_path / "team.v2.config.toml").write_text('model="file-model"\n', encoding="utf-8")
    values, _ = connection(ProviderSettings(profile="team.v2"), {"CODEX_HOME": str(tmp_path)})
    assert values["model"] == "file-model"


def test_linked_profile_cannot_escape_cli_home(tmp_path):
    """独立配置档链接到 CLI home 外时拒绝读取"""
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside.config.toml"
    outside.write_text('model="outside-canary"', encoding="utf-8")
    try:
        (home / "linked.config.toml").symlink_to(outside)
    except OSError:
        pytest.skip("当前环境不允许创建符号链接")
    with pytest.raises(ProviderError, match="CODEX_HOME 内"):
        connection(ProviderSettings(profile="linked"), {"CODEX_HOME": str(home)})


@pytest.mark.parametrize("effort", [123, ["high"], "high\nshell_tool=true", "x" * 65])
def test_inherited_effort_rejects_invalid_types_and_shapes(tmp_path, effort):
    """CLI 配置继承同样约束强度类型和格式，不将异常值作为参数发送"""
    (tmp_path / "config.toml").write_text(
        "model_reasoning_effort=" + json.dumps(effort), encoding="utf-8"
    )
    with pytest.raises(ProviderError, match="无法读取 CLI 连接配置"):
        connection(ProviderSettings(), {"CODEX_HOME": str(tmp_path)})


def test_custom_model_catalog_retains_the_same_tool_restrictions(tmp_path):
    """任意供应商模型名称原样进入目录，模型名称不改变工具和执行能力"""
    (tmp_path / "control").mkdir()
    model = "provider/custom-model:2027"
    path = write_catalog(tmp_path, {"model": model})
    with open(path, encoding="utf-8") as stream:
        entry = json.load(stream)["models"][0]
    assert entry["slug"] == model
    assert entry["shell_type"] == "disabled"
    assert entry["apply_patch_tool_type"] is None
    assert entry["node_repl_disabled"] is True
    assert entry["experimental_supported_tools"] == []
