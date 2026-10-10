"""内置清单、发行策略和声明式产品组合发现"""

import json
from pathlib import Path

from resume_maker.runtime.graph import PluginError
from resume_maker.sdk.manifest import Manifest

ROOT = Path(__file__).parent
PACKAGES = ROOT.parent / "plugin_packages"


def package_definitions():
    """扫描独立目录的声明和组合归属，发现阶段不执行插件代码"""
    for path in sorted(PACKAGES.glob("*/manifest.json")):
        manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
        metadata = json.loads(path.with_name("package.json").read_text(encoding="utf-8"))
        if path.parent.name != manifest.id.replace(".", "_").replace("-", "_"):
            raise PluginError(f"插件目录身份不一致：{manifest.id}")
        yield manifest, metadata["resumeMaker"].get("profiles", [])


def discover() -> tuple[dict[str, Manifest], set[str], dict[str, list[str]]]:
    """只读取数据文件，不导入插件入口"""
    policy = json.loads((ROOT / "profiles.json").read_text(encoding="utf-8"))
    manifests = {}
    profiles = {name: list(values) for name, values in policy["profiles"].items()}
    for manifest, memberships in package_definitions():
        if manifest.id in manifests:
            raise PluginError(f"重复插件定义：{manifest.id}")
        manifests[manifest.id] = manifest
        for name in memberships:
            if name not in profiles:
                raise PluginError(f"插件 {manifest.id} 引用未知产品组合：{name}")
            profiles[name].append(manifest.id)
    required = set(policy["required"])
    if required - manifests.keys():
        raise PluginError("发行包缺少必需插件清单")
    return manifests, required, profiles


def selection(profile: str, overrides: tuple[str, ...] | None = None):
    """显式配置代表完整组合，系统完整性由求解器再次核验"""
    manifests, required, profiles = discover()
    if profile not in profiles:
        raise PluginError(f"未知产品组合：{profile}")
    return manifests, set(overrides if overrides is not None else profiles[profile]), required


def configuration_bundles(profile):
    """按产品组合声明顺序读取配置包，组合配置不改变系统必需约束"""
    policy = json.loads((ROOT / "profiles.json").read_text(encoding="utf-8"))
    bundles = policy.get("bundles", {})
    return [
        {"name": "bundle:" + name, "edits": bundles[name]}
        for name in policy.get("profile_bundles", {}).get(profile, [])
    ]
