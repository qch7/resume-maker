"""纯清单依赖求解和发行完整性验证"""

from dataclasses import dataclass

from resume_maker.sdk.manifest import Dependency, Manifest, compatible


class PluginError(RuntimeError):
    """包含插件和阶段的可操作错误"""


@dataclass(frozen=True)
class Resolution:
    """激活顺序、依赖边和已选择的能力所有者"""

    order: tuple[str, ...]
    edges: dict[str, frozenset[str]]
    providers: dict[str, str]
    collections: dict[str, tuple[str, ...]]
    bindings: dict[tuple[str, str, str], tuple[str, ...]]
    client_order: tuple[str, ...]


def available_selection(manifests, desired, required, unavailable=None, environments=None):
    """缺少可选安装时保留期望配置，逐层阻断依赖且不自动替换提供方"""
    from resume_maker.runtime.packages import check_dependencies

    blocked = dict(unavailable or {})
    for key in desired:
        if key not in manifests:
            blocked.setdefault(key, "插件代码未安装，资料和配置已保留")
        elif missing := check_dependencies(
            manifests[key], versions=(environments or {}).get(key, {}).get("versions")
        ):
            blocked[key] = "缺少依赖：" + "; ".join(missing)
    selected = desired - blocked.keys()
    while True:
        removed = set()
        services = {
            domain: {
                name: {key for key in selected if name in manifests[key].provides.get(domain, {})}
                for key in selected
                for name in manifests[key].provides.get(domain, {})
            }
            for domain in ("host", "client")
        }
        for key in selected:
            manifest = manifests[key]
            missing = set(manifest.plugins.keys() - selected)
            for domain, requirements in manifest.requires.items():
                for name, raw in requirements.items():
                    requirement = Dependency(version=raw) if isinstance(raw, str) else raw
                    providers = services["host" if domain == "remote" else domain].get(name, set())
                    if requirement.provider:
                        providers = providers & {requirement.provider}
                    if not providers:
                        missing.add(f"{domain}/{name}")
            if missing:
                blocked[key] = "依赖不可用：" + ", ".join(sorted(missing))
                removed.add(key)
        if not removed:
            break
        selected -= removed
    resolve(manifests, selected, required)
    return selected, blocked


def topological(edges, label):
    """每个执行域分别求序，客户端不能让宿主等待浏览器启动"""
    order, pending = [], set(edges)
    while pending:
        ready = sorted(key for key in pending if not (edges[key] & pending))
        if not ready:
            chain = "; ".join(
                f"{key} -> {','.join(sorted(edges[key] & pending))}" for key in sorted(pending)
            )
            raise PluginError(f"{label} 插件依赖成环：{chain}")
        order.extend(ready)
        pending.difference_update(ready)
    return tuple(order)


def resolve(manifests: dict[str, Manifest], selected: set[str], required: set[str]) -> Resolution:
    """独立验证 Host、Client 和远端依赖的版本、基数及生命周期作用域"""
    if missing := required - selected:
        raise PluginError(f"必需插件不能缺席或停用：{', '.join(sorted(missing))}")
    if missing := selected - manifests.keys():
        raise PluginError(f"插件尚未安装：{', '.join(sorted(missing))}")
    indexes = {domain: {} for domain in ("host", "client")}
    graphs = {domain: {key: set() for key in selected} for domain in indexes}
    edges = {key: set() for key in selected}
    scopes = {"application": 0, "workspace": 1, "task": 2}
    for identifier in sorted(selected):
        manifest = manifests[identifier]
        if manifest.instances.multiple or manifest.instances.scope == "task":
            raise PluginError(
                f"{identifier} 请求了当前本地 Host 不支持的多实例或任务级实例，"
                "请使用工作区单实例和 sys.jobs 任务作用域"
            )
        for domain, constraint in (("host", manifest.host_api), ("client", manifest.client_api)):
            if not compatible("1.0.0", constraint):
                raise PluginError(f"{identifier} 与 {domain} API 1.0.0 不兼容")
            for name, spec in manifest.provides.get(domain, {}).items():
                owners = indexes[domain].setdefault(name, [])
                if owners and (
                    spec.cardinality != "many"
                    or any(
                        manifests[owner].provides[domain][name].cardinality != "many"
                        for owner in owners
                    )
                ):
                    raise PluginError(
                        f"能力 {domain}/{name} 冲突：{','.join([*owners, identifier])}"
                    )
                owners.append(identifier)
    bindings = {}
    for identifier in sorted(selected):
        manifest = manifests[identifier]
        for dependency, constraint in manifest.plugins.items():
            if dependency not in selected or not compatible(
                manifests[dependency].version, constraint
            ):
                raise PluginError(f"{identifier} 需要插件 {dependency} {constraint}")
            if dependency != identifier:
                edges[identifier].add(dependency)
                graphs["host"][identifier].add(dependency)
        groups = {domain: dict(values) for domain, values in manifest.requires.items()}
        groups.setdefault("host", {}).update(
            {name: value for name, value in manifest.optional.items() if name in indexes["host"]}
        )
        for domain, requirements in groups.items():
            provider_domain = "host" if domain == "remote" else domain
            for name, raw in requirements.items():
                dependency = Dependency(version=raw) if isinstance(raw, str) else raw
                owners = list(indexes[provider_domain].get(name, []))
                if dependency.provider:
                    owners = [owner for owner in owners if owner == dependency.provider]
                if not owners:
                    raise PluginError(f"{identifier} 缺少能力 {domain}/{name} {dependency.version}")
                if dependency.cardinality == "one" and len(owners) != 1:
                    raise PluginError(
                        f"{identifier} 的 {name} 需要明确选择提供方：{','.join(owners)}"
                    )
                for owner in owners:
                    spec = manifests[owner].provides[provider_domain][name]
                    if not compatible(spec.version, dependency.version):
                        raise PluginError(
                            f"{identifier} 需要 {name} {dependency.version}，实际 {spec.version}"
                        )
                    if (
                        domain == "host"
                        and scopes[manifest.instances.scope]
                        < scopes[manifests[owner].instances.scope]
                    ):
                        raise PluginError(f"{identifier} 的作用域不能持有更短生命周期的 {owner}")
                    if owner != identifier:
                        edges[identifier].add(owner)
                        if domain in graphs:
                            graphs[domain][identifier].add(owner)
                bindings[(identifier, domain, name)] = tuple(owners)
    providers = {
        name: owners[0]
        for name, owners in indexes["host"].items()
        if manifests[owners[0]].provides["host"][name].cardinality == "one"
    }
    collections = {
        name: tuple(owners) for name, owners in indexes["host"].items() if name not in providers
    }
    for identifier in selected:
        for name in manifests[identifier].enhances:
            if (
                name not in manifests[identifier].requires.get("host", {})
                and name not in manifests[identifier].optional
            ):
                raise PluginError(f"{identifier} 的增强目标 {name} 必须声明依赖")
            for owner in indexes["host"].get(name, []):
                if owner != identifier:
                    edges[owner].add(identifier)
    return Resolution(
        topological(graphs["host"], "Host"),
        {key: frozenset(value) for key, value in edges.items()},
        providers,
        collections,
        bindings,
        topological(graphs["client"], "Client"),
    )
