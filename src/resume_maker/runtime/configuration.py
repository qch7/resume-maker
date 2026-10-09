"""插件配置在执行代码前按清单校验，运行实例只收到独立快照"""

import re
from copy import deepcopy
from math import isfinite

from jsonschema import Draft202012Validator
from jsonschema.validators import extend

from resume_maker.infrastructure.observability import protect_secrets
from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.state import fingerprint
from resume_maker.runtime.worker import validate_schema
from resume_maker.sdk.configuration import ConfigurationEdit, ConfigurationLayer

STRICT_CONFIG_VALIDATOR = extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine_many(
        {
            "integer": lambda _checker, value: type(value) is int,
            "number": lambda _checker, value: (
                type(value) is int or (type(value) is float and isfinite(value))
            ),
        }
    ),
)


def configurations(manifests, overrides):
    """配置按对象整体替换，未指定项采用清单默认值"""
    unknown = set(overrides) - manifests.keys()
    if unknown:
        raise PluginError(f"配置引用未知插件：{', '.join(sorted(unknown))}")
    result = {}
    for identifier, manifest in manifests.items():
        validate_schema(manifest.config_schema)
        Draft202012Validator.check_schema(manifest.config_schema)
        value = deepcopy(overrides.get(identifier, manifest.config))
        for name in manifest.credential_fields:
            reference = value.get(name, "") if isinstance(value, dict) else None
            if not isinstance(reference, str) or (
                reference and not re.fullmatch(r"cred\.[a-f0-9]{32}", reference)
            ):
                if isinstance(reference, str):
                    protect_secrets(reference)
                raise PluginError(f"{identifier} 的凭据字段 {name} 只能保存宿主凭据引用")
        if isinstance(value, dict):
            for key, declaration in manifest.config_schema.get("properties", {}).items():
                if (
                    key not in value
                    and key not in manifest.config_schema.get("required", ())
                    and isinstance(declaration, dict)
                    and "default" in declaration
                ):
                    value[key] = deepcopy(declaration["default"])
        validator = (
            STRICT_CONFIG_VALIDATOR
            if manifest.config_schema.get("x-resume-maker-strict")
            else Draft202012Validator
        )
        errors = list(validator(manifest.config_schema).iter_errors(value))
        if errors:
            paths = [".".join(map(str, error.absolute_path)) or "$" for error in errors[:10]]
            raise PluginError(f"{identifier} 的配置不符合 schema，字段：{', '.join(paths)}")
        result[identifier] = value
    return result


def replacement_layer(name, configs):
    """把整份配置转换为明确替换操作"""
    return {
        "name": name,
        "edits": [
            {"instance": key, "operation": "replace", "value": value}
            for key, value in configs.items()
        ],
    }


def compose_configuration(manifests, layers, *, missing_ok=False):
    """依序应用配置并返回字段来源、摘要及空冲突列表，冲突直接拒绝候选"""
    values = {key: deepcopy(manifest.config) for key, manifest in manifests.items()}
    origins = {key: field_origins(value, "default") for key, value in values.items()}
    parsed, names = [], set()
    for raw in layers:
        layer = ConfigurationLayer.model_validate(raw)
        if layer.name in names or layer.name == "default":
            raise PluginError(f"配置层名称重复或保留：{layer.name}")
        names.add(layer.name)
        lower, lower_origins = deepcopy(values), deepcopy(origins)
        for edit in layer.edits:
            identifier = edit.instance
            if identifier not in manifests:
                if missing_ok:
                    continue
                raise PluginError(f"配置引用未知实例：{identifier}")
            if edit.operation == "replace":
                values[identifier] = deepcopy(edit.value)
                origins[identifier] = field_origins(edit.value, layer.name)
                continue
            if not edit.path:
                values[identifier] = deepcopy(lower[identifier])
                origins[identifier] = deepcopy(lower_origins[identifier])
                continue
            validate_path(manifests[identifier].config_schema, edit.path)
            pointer = tuple(edit.path)
            origins[identifier] = {
                path: owner
                for path, owner in origins[identifier].items()
                if not path[: len(pointer)] == pointer and path != ()
            }
            if edit.operation == "set":
                set_path(values[identifier], edit.path, deepcopy(edit.value))
                origins[identifier].update(field_origins(edit.value, layer.name, pointer))
            else:
                present, value = read_path(lower[identifier], edit.path)
                set_path(values[identifier], edit.path, deepcopy(value), remove=not present)
                origins[identifier].update(
                    {
                        path: owner
                        for path, owner in lower_origins[identifier].items()
                        if path[: len(pointer)] == pointer
                    }
                )
        parsed.append(layer.model_dump(mode="json", exclude_unset=True))
    values = configurations(manifests, values)
    provenance = {
        key: {
            "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in path): owner
            for path, owner in sorted(
                (path, paths.get(path, "default")) for path in field_origins(values[key], "default")
            )
        }
        for key, paths in origins.items()
    }
    return {
        "configs": values,
        "provenance": provenance,
        "layers": parsed,
        "conflicts": [],
        "digest": fingerprint({"configs": values, "layers": parsed}),
    }


def field_origins(value, owner, path=()):
    """数组作为一个字段，空对象也保留整体来源"""
    if isinstance(value, dict) and value:
        result = {}
        for key, child in value.items():
            result.update(field_origins(child, owner, (*path, key)))
        return result
    return {path: owner}


def validate_path(schema, path):
    """字段操作只进入 schema 允许的对象属性，不按数组下标隐式合并"""
    root = schema
    for key in path:
        for _ in range(20):
            if "$ref" not in schema:
                break
            reference = schema["$ref"]
            if not reference.startswith("#/"):
                raise PluginError("配置字段引用无效")
            schema = root
            for part in reference[2:].split("/"):
                schema = schema[part.replace("~1", "/").replace("~0", "~")]
        else:
            raise PluginError("配置字段引用层级过深")
        if schema.get("type") not in (None, "object"):
            raise PluginError("字段操作只允许对象属性，数组请整体设置")
        properties = schema.get("properties", {})
        if key in properties:
            schema = properties[key]
        elif schema.get("additionalProperties", True) is not False:
            schema = schema.get("additionalProperties", {})
            if schema is True:
                schema = {}
        else:
            raise PluginError(f"schema 未声明配置字段：{key}")


def read_path(value, path):
    """区分属性缺失和业务 null"""
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


def set_path(value, path, replacement, *, remove=False):
    """只建立对象层级，重置缺失值不制造空父节点"""
    for key in path[:-1]:
        if key not in value:
            if remove:
                return
            value[key] = {}
        if not isinstance(value[key], dict):
            raise PluginError("配置字段的父级不是对象")
        value = value[key]
    if remove:
        value.pop(path[-1], None)
    else:
        value[path[-1]] = replacement


def workspace_layers(layers, configs=None, edits=()):
    """仅修改工作区覆盖，启动覆盖继续具有最高优先级"""
    result = deepcopy(layers)
    workspace = next((layer for layer in result if layer["name"] == "workspace"), None)
    if workspace is None:
        workspace = {"name": "workspace", "edits": []}
        startup = next(
            (i for i, layer in enumerate(result) if layer["name"] == "startup"), len(result)
        )
        result.insert(startup, workspace)
    replacements = replacement_layer("workspace", configs or {})["edits"]
    additions = [
        ConfigurationEdit.model_validate(edit).model_dump(mode="json", exclude_unset=True)
        for edit in edits
    ]
    workspace["edits"] = [*workspace["edits"], *replacements, *additions]
    return result


def startup_configuration(saved, path=None, bundles=()):
    """读取非执行配置文件，启动覆盖只作用于当前进程"""
    import json

    from pydantic import Field

    from resume_maker.sdk.manifest import Contract

    class Input(Contract):
        """配置文件只能定义有序默认组合和本次启动覆盖"""

        bundles: tuple[ConfigurationLayer, ...] = Field(default=(), max_length=100)
        startup: tuple[ConfigurationEdit, ...] = Field(default=(), max_length=10000)

    saved = saved or {}
    layers = deepcopy(saved.get("config_layers", [*bundles, replacement_layer("workspace", {})]))
    if path is not None:
        source = Input.model_validate(json.loads(path.read_text(encoding="utf-8")))
        configured = [
            {**layer.model_dump(mode="json", exclude_unset=True), "name": "bundle:" + layer.name}
            for layer in source.bundles
        ]
        layers = [
            *bundles,
            *configured,
            *[layer for layer in layers if layer["name"] == "workspace"],
        ]
        layers.append(
            {
                "name": "startup",
                "edits": [
                    edit.model_dump(mode="json", exclude_unset=True) for edit in source.startup
                ],
            }
        )
    return layers
