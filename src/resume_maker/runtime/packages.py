"""本机插件包检查、不可变安装和保留资料的卸载"""

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from resume_maker.infrastructure.filesystem import publish_directory
from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.state import StateStore, fingerprint
from resume_maker.sdk.manifest import Manifest


def safe_member(name: str) -> PurePosixPath:
    """只接受规范相对包路径，拒绝平台设备名和链接逃逸"""
    path = PurePosixPath(name)
    devices = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(10)),
        *(f"lpt{i}" for i in range(10)),
    }
    if (
        path.is_absolute()
        or not path.parts
        or path.as_posix() != name
        or any(
            part in {".", ".."}
            or part.endswith((".", " "))
            or part.split(".")[0].lower() in devices
            for part in path.parts
        )
        or any(char in name for char in ("\\", ":", "\x00"))
    ):
        raise PluginError("插件包包含无效路径")
    return path


def check_dependencies(manifest: Manifest, *, versions=None) -> list[str]:
    """使用 PEP 440 核验共享解释器依赖，不修改正在运行的环境"""
    missing = []
    installed_versions = (
        {canonicalize_name(key): value for key, value in versions.items()}
        if versions is not None
        else None
    )
    for value in manifest.dependencies:
        requirement = Requirement(value)
        if requirement.url:
            raise PluginError("运行依赖必须使用锁定包名及版本，不能携带任意 URL")
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            if installed_versions is not None:
                installed = installed_versions.get(canonicalize_name(requirement.name))
                if installed is None:
                    missing.append(value)
                    continue
            else:
                installed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(value)
        else:
            if installed not in requirement.specifier:
                missing.append(f"{value}（当前 {installed}）")
    return missing


class PackageStore:
    """安装只处理数据文件，激活或维护前才允许执行已授权代码"""

    def __init__(self, directory: Path, reserved: set[str]):
        """安装区独立于可备份资料和运行解释器"""
        self.root = directory / "plugin-packages"
        self.index = directory / "plugin-packages.json"
        self.reserved = reserved
        self.writer = StateStore(directory)

    def records(self):
        """读取已提交安装目录，尚未启用的包同样可查询"""
        if not self.index.exists():
            return {}
        value = json.loads(self.index.read_text(encoding="utf-8"))
        if value.get("version") != 1:
            raise PluginError("插件安装目录版本不受支持")
        return value["packages"]

    def inspect(self, path: Path):
        """读取完整摘要清单并检查所有文件，不导入模块或运行安装脚本"""
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 4096 or sum(item.file_size for item in entries) > 256 * 1024 * 1024:
                raise PluginError("插件包超过文件数量或解压大小限制")
            names = set()
            folded = set()
            for item in entries:
                if item.is_dir():
                    continue
                safe_member(item.filename)
                if item.filename.casefold() in folded:
                    raise PluginError("插件包存在重复或大小写冲突路径")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise PluginError("插件包不能包含符号链接")
                folded.add(item.filename.casefold())
                names.add(item.filename)
            if not {"manifest.json", "artifacts.json", "LICENSE"} <= names:
                raise PluginError("插件包缺少 manifest、artifacts 或许可证")
            manifest = Manifest.model_validate_json(archive.read("manifest.json"))
            if manifest.id in self.reserved or manifest.id.startswith(("sys.", "provider.")):
                raise PluginError("外部插件不能占用系统及内置插件身份")
            artifacts = json.loads(archive.read("artifacts.json"))
            if set(artifacts) != names - {"artifacts.json"}:
                raise PluginError("插件包存在未登记文件或缺失产物")
            for name, expected in artifacts.items():
                raw = archive.read(name)
                if (
                    len(raw) != expected["size"]
                    or hashlib.sha256(raw).hexdigest() != expected["sha256"]
                ):
                    raise PluginError(f"插件包摘要不匹配：{name}")
            for domain, entry in manifest.entrypoints.items():
                relative = entry.entry.partition(":")[0] if domain != "client" else entry.entry
                safe_member(relative)
                if relative not in artifacts:
                    raise PluginError(f"插件入口未登记到产物清单：{relative}")
            if manifest.environment_lock and manifest.environment_lock not in artifacts:
                raise PluginError("环境锁必须登记到插件产物清单")
            return {
                "manifest": manifest.model_dump(),
                "digest": fingerprint(artifacts),
                "artifacts": artifacts,
                "missing_dependencies": check_dependencies(manifest),
                "trust_modes": sorted({entry.mode for entry in manifest.entrypoints.values()}),
            }

    def install(self, path: Path, expected_digest: str, trusted_modes: set[str]):
        """仅安装已审查的相同产物，代码和依赖不会注入活动解释器"""
        inspection = self.inspect(path)
        if inspection["digest"] != expected_digest:
            raise PluginError("插件包在审查后发生变化，请重新生成安装计划")
        if set(inspection["trust_modes"]) - trusted_modes:
            raise PluginError("插件代码的执行信任尚未明确授予")
        manifest = Manifest.model_validate(inspection["manifest"])
        records = self.records()
        previous = records.get(manifest.id)
        if (
            previous
            and previous["version"] == manifest.version
            and previous["digest"] != expected_digest
        ):
            raise PluginError("同版本插件出现不同产物，发布者须提升版本")
        target = self.root / manifest.id / expected_digest
        if not target.exists():
            staging = self.root / f".staging-{uuid4()}"
            staging.mkdir(parents=True)
            try:
                with ZipFile(path) as archive:
                    for name in (*inspection["artifacts"], "artifacts.json"):
                        destination = staging / Path(*safe_member(name).parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        data = archive.read(name)
                        if name == "artifacts.json":
                            if fingerprint(json.loads(data)) != expected_digest:
                                raise PluginError("安装期间包摘要发生变化")
                        else:
                            expected = inspection["artifacts"][name]
                            if hashlib.sha256(data).hexdigest() != expected["sha256"]:
                                raise PluginError("安装期间包内容发生变化")
                        with destination.open("xb") as output:
                            output.write(data)
                            output.flush()
                            os.fsync(output.fileno())
                target.parent.mkdir(parents=True, exist_ok=True)
                publish_directory(staging, target)
            finally:
                if staging.exists() and staging.resolve().parent == self.root.resolve():
                    shutil.rmtree(staging)
        records[manifest.id] = {
            "version": manifest.version,
            "digest": expected_digest,
            "trusted_modes": sorted(trusted_modes),
            "previous": previous,
        }
        self.writer.write(self.index, {"version": 1, "packages": records})
        return {
            "id": manifest.id,
            "installed": True,
            "enabled": False,
            "missing_dependencies": inspection["missing_dependencies"],
        }

    def discover(self, *, strict=True):
        """逐包验证，恢复模式保留不可用原因而不阻止系统资料访问"""
        manifests, locations = {}, {}
        self.failures = {}
        for identifier, record in self.records().items():
            try:
                manifest, directory = self._discover_one(identifier, record)
                manifests[identifier], locations[identifier] = manifest, directory
            except (PluginError, OSError, ValueError, KeyError) as exc:
                if strict:
                    raise
                self.failures[identifier] = f"安装产物不可用：{type(exc).__name__}"
        return manifests, locations

    def _discover_one(self, identifier, record):
        """核验单个已安装包的完整摘要、身份和信任"""
        if identifier in self.reserved or identifier.startswith(("sys.", "provider.")):
            raise PluginError("安装目录试图覆盖受保护插件")
        safe_member(identifier)
        if not isinstance(record["digest"], str) or not re.fullmatch(
            r"[a-f0-9]{64}", record["digest"]
        ):
            raise PluginError("安装目录摘要无效")
        directory = (self.root / identifier / record["digest"]).resolve()
        if not directory.is_relative_to(self.root.resolve()):
            raise PluginError("安装目录越界")
        index = json.loads((directory / "artifacts.json").read_text(encoding="utf-8"))
        if fingerprint(index) != record["digest"]:
            raise PluginError(f"已安装插件清单发生变化：{identifier}")
        for name, expected in index.items():
            path = directory.joinpath(*safe_member(name).parts)
            if path.is_symlink() or not path.resolve().is_relative_to(directory):
                raise PluginError("已安装插件资源越界")
            if (
                path.stat().st_size != expected["size"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]
            ):
                raise PluginError(f"已安装插件产物发生变化：{identifier}/{name}")
        manifest = Manifest.model_validate_json((directory / "manifest.json").read_bytes())
        if manifest.id != identifier or manifest.version != record["version"]:
            raise PluginError("安装目录身份不匹配")
        if {entry.mode for entry in manifest.entrypoints.values()} - set(record["trusted_modes"]):
            raise PluginError("已安装插件缺少执行信任")
        return manifest, directory

    def uninstall(self, identifier: str, active: set[str]):
        """先移除未激活包的安装引用，资料和已加载代码等待独立回收"""
        if identifier in active:
            raise PluginError("请先通过变更计划停用插件及其依赖")
        records = self.records()
        if identifier not in records:
            raise PluginError("该插件没有外部安装记录")
        records.pop(identifier)
        self.writer.write(self.index, {"version": 1, "packages": records})
        return {"id": identifier, "installed": False, "data_retained": True}
