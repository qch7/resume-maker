"""插件配置在执行代码前按清单校验，运行实例只收到独立快照"""

from copy import deepcopy

from jsonschema import Draft202012Validator

from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.worker import validate_schema


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
        errors = list(Draft202012Validator(manifest.config_schema).iter_errors(value))
        if errors:
            paths = [".".join(map(str, error.absolute_path)) or "$" for error in errors[:10]]
            raise PluginError(f"{identifier} 的配置不符合 schema，字段：{', '.join(paths)}")
        result[identifier] = value
    return result
