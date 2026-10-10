"""能力分组的候选选择，实际切换仍经过完整变更计划"""

from resume_maker.runtime.graph import PluginError, resolve
from resume_maker.sdk.manifest import Dependency, compatible


def capability_groups(manifest, manifests):
    """旧提供方沿用相同服务的已声明分类，不按公共依赖推断业务领域"""
    if manifest.capability_groups:
        return manifest.capability_groups
    services = {(domain, name) for domain, values in manifest.provides.items() for name in values}
    groups = {}
    for other in manifests.values():
        if any(name in other.provides.get(domain, {}) for domain, name in services):
            for group in other.capability_groups:
                groups.setdefault(group.id, group)
    return list(groups.values())


def owners(manifests, selected, domain, name, dependency):
    """按执行域、显式绑定及版本找出候选提供方"""
    domain = "host" if domain == "remote" else domain
    return {
        key
        for key in selected
        if (not dependency.provider or key == dependency.provider)
        and (spec := manifests[key].provides.get(domain, {}).get(name))
        and compatible(spec.version, dependency.version)
    }


def requirements(manifest):
    """只枚举硬依赖，集合消费及可选增强不要求同时启用"""
    for domain, values in manifest.requires.items():
        for name, raw in values.items():
            yield domain, name, Dependency(version=raw) if isinstance(raw, str) else raw


def select_capability_group(manifests, selected, required, group, enabled):
    """整组选择补齐明确依赖，停用逐层移除消费者并保护必需插件"""
    selected = set(selected)
    if missing := selected - manifests.keys():
        raise PluginError(f"插件尚未安装：{', '.join(sorted(missing))}")
    members = {
        key
        for key, manifest in manifests.items()
        if any(item.id == group for item in capability_groups(manifest, manifests))
        and manifest.instances.scope != "task"
    }
    if not members:
        raise PluginError("能力分类不存在或仅支持任务实例")
    members -= required
    if enabled:
        existing = set(selected)
        for key in sorted(members - selected):
            # 已选择的提供方继续负责唯一能力，整组启用不替换供应商
            services = [
                (domain, name, spec)
                for domain, values in manifests[key].provides.items()
                for name, spec in values.items()
            ]
            if services and all(
                spec.cardinality == "one"
                and any(name in manifests[owner].provides.get(domain, {}) for owner in existing)
                for domain, name, spec in services
            ):
                continue
            selected.add(key)
        while True:
            added = set()
            for key in sorted(selected):
                manifest = manifests[key]
                for plugin in manifest.plugins.keys() - selected:
                    if plugin not in manifests or manifests[plugin].instances.scope == "task":
                        raise PluginError(f"{manifest.title} 的依赖插件尚未安装：{plugin}")
                    added.add(plugin)
                for domain, name, dependency in requirements(manifest):
                    if owners(manifests, selected, domain, name, dependency):
                        continue
                    available = owners(
                        manifests,
                        {k for k, m in manifests.items() if m.instances.scope != "task"},
                        domain,
                        name,
                        dependency,
                    )
                    if not available:
                        raise PluginError(f"{manifest.title} 缺少能力 {domain}/{name}")
                    if len(available) > 1 and dependency.cardinality != "many":
                        raise PluginError(f"请先为 {domain}/{name} 选择一个提供方，再启用整组能力")
                    added.update(available)
            added -= selected
            if not added:
                break
            selected.update(added)
    else:
        selected -= members
        while True:
            removed = {
                key
                for key in selected
                if manifests[key].plugins.keys() - selected
                or any(
                    not owners(manifests, selected, domain, name, dependency)
                    for domain, name, dependency in requirements(manifests[key])
                )
            }
            if removed & required:
                raise PluginError("此能力仍由基础插件使用，不能整组停用。")
            if not removed:
                break
            selected -= removed
    resolve(manifests, selected, required)
    return sorted(selected)
