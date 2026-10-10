"""把不可变插件定义展开为具有独立配置和服务绑定的运行实例"""

from copy import deepcopy

from resume_maker.runtime.graph import PluginError
from resume_maker.sdk.manifest import Dependency, InstanceSpec


def expand_instances(definitions, specs=(), *, missing_ok=False):
    """保留默认实例，额外实例只引用已安装定义且不能占用保留身份"""
    manifests = dict(definitions)
    parsed = {}
    for raw in specs:
        spec = raw if isinstance(raw, InstanceSpec) else InstanceSpec.model_validate(raw)
        if spec.id in parsed:
            raise PluginError(f"实例身份重复：{spec.id}")
        definition = definitions.get(spec.plugin)
        if definition is None:
            if missing_ok:
                parsed[spec.id] = spec
                continue
            raise PluginError(f"实例 {spec.id} 的插件未安装：{spec.plugin}")
        if spec.id != spec.plugin:
            if spec.id in definitions or spec.id.startswith(("sys.", "provider.")):
                raise PluginError(f"实例不能占用已安装插件或系统身份：{spec.id}")
            if not definition.instances.multiple:
                raise PluginError(f"插件不支持多个实例：{spec.plugin}")
        requirements = deepcopy(definition.requires)
        for domain, bindings in spec.bindings.items():
            for name, owner in bindings.items():
                if name not in requirements.get(domain, {}):
                    raise PluginError(f"{spec.id} 没有声明依赖 {domain}/{name}")
                raw = requirements[domain][name]
                dependency = Dependency(version=raw) if isinstance(raw, str) else raw
                requirements[domain][name] = dependency.model_copy(update={"provider": owner})
        manifests[spec.id] = definition.model_copy(update={"id": spec.id, "requires": requirements})
        parsed[spec.id] = spec
    return manifests, parsed


def definition_id(specs, identifier):
    """安装记录按定义保存，运行和配置按实例保存"""
    return specs[identifier].plugin if identifier in specs else identifier
