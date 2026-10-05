"""配置覆盖的确定顺序、来源说明、重置及临时启动语义"""

import json

import pytest
from pydantic import ValidationError

from resume_maker.runtime.configuration import (
    compose_configuration,
    replacement_layer,
    startup_configuration,
    workspace_layers,
)
from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.state import StateStore
from resume_maker.sdk.configuration import ConfigurationEdit
from resume_maker.sdk.manifest import Manifest


def manifests():
    """配置包含可空值、可选属性、嵌套对象和整体替换的数组"""
    return {
        "community.example": Manifest.model_validate(
            {
                "id": "community.example",
                "manifest_version": 1,
                "title": "合成配置",
                "version": "1.0.0",
                "package": "synthetic",
                "config": {"nested": {"value": 1}, "list": [1, 2], "nullable": "default"},
                "config_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "nested": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"value": {"type": "integer"}},
                        },
                        "list": {"type": "array", "items": {"type": "integer"}},
                        "nullable": {"type": ["string", "null"]},
                        "optional": {"type": "string"},
                    },
                },
            }
        )
    }


def edit(operation, path=(), **extra):
    """合成一项针对固定实例的声明式字段操作"""
    return {"instance": "community.example", "operation": operation, "path": list(path), **extra}


def test_layer_order_null_reset_and_array_replacement():
    """后层覆盖前层，重置恢复同层开始前的值且 null 保留为业务值"""
    layers = [
        {"name": "bundle:base", "edits": [edit("set", ["nested", "value"], value=2)]},
        {
            "name": "workspace",
            "edits": [
                edit("set", ["nested", "value"], value=3),
                edit("set", ["nullable"], value=None),
                edit("set", ["list"], value=[9]),
                edit("set", ["optional"], value="remove"),
                edit("reset", ["optional"]),
                edit("reset", ["nested", "value"]),
            ],
        },
        {"name": "startup", "edits": [edit("set", ["nested", "value"], value=7)]},
    ]
    result = compose_configuration(manifests(), layers)
    value = result["configs"]["community.example"]
    assert value == {"nested": {"value": 7}, "nullable": None, "list": [9]}
    assert result["provenance"]["community.example"] == {
        "/nested/value": "startup",
        "/nullable": "workspace",
        "/list": "workspace",
    }
    reset = compose_configuration(manifests(), workspace_layers(layers[:-1], edits=[edit("reset")]))
    assert reset["configs"]["community.example"]["nested"]["value"] == 2
    assert reset["provenance"]["community.example"]["/nullable"] == "default"
    assert layers[1]["edits"][0]["value"] == 3
    with pytest.raises(ValidationError, match="不能携带"):
        ConfigurationEdit.model_validate(edit("reset", value=None))


def test_unknown_fields_array_indexes_and_duplicate_layers_are_rejected():
    """无效候选不能靠配置合并掩盖 schema 错误"""
    for edits in (
        [edit("set", ["unknown"], value=1)],
        [edit("set", ["list", "0"], value=2)],
        [edit("set", ["nested", "value"], value="wrong")],
    ):
        with pytest.raises(PluginError):
            compose_configuration(manifests(), [{"name": "workspace", "edits": edits}])
    with pytest.raises(PluginError, match="重复"):
        compose_configuration(manifests(), [{"name": "workspace"}, {"name": "workspace"}])


def test_startup_override_is_not_written_as_workspace_setting(tmp_path):
    """临时启动值不会在下一次普通启动时变成用户永久配置"""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "bundles": [{"name": "test", "edits": [edit("set", ["nullable"], value="bundle")]}],
                "startup": [edit("set", ["nullable"], value="once")],
            }
        ),
        encoding="utf-8",
    )
    result = compose_configuration(manifests(), startup_configuration({}, path))
    assert result["configs"]["community.example"]["nullable"] == "once"
    store = StateStore(tmp_path)
    store.commit(["community.example"], 2, {}, result["configs"], config_layers=result["layers"])
    restored = compose_configuration(manifests(), startup_configuration(store.read()))
    assert restored["configs"]["community.example"]["nullable"] == "bundle"
    assert restored["provenance"]["community.example"]["/nullable"] == "bundle:test"
    assert startup_configuration({}) == [replacement_layer("workspace", {})]
