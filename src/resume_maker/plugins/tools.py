"""独立插件的构建前校验、打包及离线依赖锁生成"""

import argparse
import hashlib
import json
import tempfile
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.packages import PackageStore, safe_member
from resume_maker.sdk.manifest import Manifest, compatible
from resume_maker.sdk.model import ProviderError
from resume_maker.sdk.ocr import validate_ocr_document
from resume_maker.sdk.version import CLIENT_API_VERSION, HOST_API_VERSION


def source_manifest(source):
    """构建前明确拒绝保留身份及不兼容的 SDK 版本"""
    manifest = Manifest.model_validate_json((source / "manifest.json").read_bytes())
    if manifest.id.startswith(("sys.", "provider.")):
        raise PluginError("外部插件使用 community 等自有身份，sys.* 和 provider.* 为保留前缀")
    for version, constraint in (
        (HOST_API_VERSION, manifest.host_api),
        (CLIENT_API_VERSION, manifest.client_api),
    ):
        if not compatible(version, constraint):
            raise PluginError(f"当前 SDK {version} 不满足插件声明 {constraint}")
    return manifest


def package_source(source: Path, output: Path, includes=()):
    """只打包必需入口和明确发布文件，拒绝链接及未授权目录遍历"""
    source = source.resolve()
    manifest = source_manifest(source)
    names = {"manifest.json", "LICENSE", *includes}
    for domain, entry in manifest.entrypoints.items():
        names.add(entry.entry if domain == "client" else entry.entry.partition(":")[0])
    if manifest.environment_lock:
        names.add(manifest.environment_lock)
        lock_path = source.joinpath(*safe_member(manifest.environment_lock).parts)
        specification = json.loads(lock_path.read_text(encoding="utf-8"))
        names.update(item["file"] for item in specification["wheels"])
    if manifest.data:
        names.update(manifest.data.schemas)
        names.update(manifest.data.relations)
        names.update(manifest.data.migrations)
        if manifest.data.descriptor:
            names.add(manifest.data.descriptor)
    files = {}
    total = 0
    if len(names) > 4095:
        raise PluginError("插件发布文件超过数量上限")
    for name in sorted(names):
        relative = safe_member(name)
        path = source.joinpath(*relative.parts)
        if any(
            source.joinpath(*relative.parts[:index]).is_symlink()
            for index in range(1, len(relative.parts) + 1)
        ):
            raise PluginError(f"发布文件不能包含链接：{name}")
        if not path.is_file() or not path.resolve().is_relative_to(source):
            raise PluginError(f"发布文件不存在或超出源码目录：{name}")
        total += path.stat().st_size
        if total > 256 * 1024 * 1024:
            raise PluginError("插件发布文件超过包大小上限")
        files[name] = path.read_bytes()
    files["artifacts.json"] = json.dumps(
        {
            name: {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in files.items()
        }
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise PluginError("输出文件已存在，请使用新文件名")
    with tempfile.TemporaryDirectory(prefix="plugin-package-", dir=output.parent) as temporary:
        candidate = Path(temporary) / "candidate.rmp"
        with ZipFile(candidate, "w", compression=ZIP_DEFLATED) as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
        inspection = PackageStore(Path(temporary), set()).inspect(candidate)
        with output.open("xb") as target:
            target.write(candidate.read_bytes())
    return inspection


def environment_lock(source: Path, wheels: Path, output: Path):
    """验证当前平台的完整 wheel 闭包，Host 插件同时锁定宿主及其依赖"""
    source, wheels = source.resolve(), wheels.resolve()
    manifest = source_manifest(source)
    if not wheels.is_relative_to(source):
        raise PluginError("离线 wheel 目录须位于插件源码内")
    tags = set(sys_tags())
    available = {}
    for path in sorted(wheels.glob("*.whl")):
        if path.is_symlink():
            raise PluginError("环境 wheel 不能使用符号链接")
        name, version, _, supported = parse_wheel_filename(path.name)
        if not tags & supported:
            continue
        if name in available:
            raise PluginError(f"当前平台同一包须只提供一个 wheel：{name}")
        with ZipFile(path) as archive:
            metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise PluginError("wheel 必须包含唯一 METADATA")
            record = BytesParser().parsebytes(archive.read(metadata[0]))
            if canonicalize_name(record["Name"]) != name or Version(record["Version"]) != version:
                raise PluginError("wheel 文件名和 METADATA 不一致")
            dependencies = record.get_all("Requires-Dist", [])
        available[name] = (path, version, dependencies)
    queue = [Requirement(value) for value in manifest.dependencies]
    if "host" in manifest.entrypoints:
        queue.append(Requirement("resume-maker"))
    selected, processed = {}, set()
    while queue:
        requirement = queue.pop()
        if requirement.marker and not requirement.marker.evaluate():
            continue
        name = canonicalize_name(requirement.name)
        if requirement.url or name not in available:
            raise PluginError(f"离线环境缺少二进制依赖：{requirement.name}")
        path, version, dependencies = available[name]
        if version not in requirement.specifier:
            raise PluginError(f"离线环境版本冲突：{requirement.name} {version}")
        extras = requirement.extras | {""}
        selected[name] = path, version
        for extra in extras:
            if (name, extra) in processed:
                continue
            processed.add((name, extra))
            for raw in dependencies:
                dependency = Requirement(raw)
                environment = {**default_environment(), "extra": extra}
                if dependency.marker is None or dependency.marker.evaluate(environment):
                    queue.append(Requirement(str(dependency).partition(";")[0]))
    result = {
        "version": 1,
        "wheels": [
            {
                "name": name,
                "version": str(version),
                "file": path.relative_to(source).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, (path, version) in sorted(selected.items())
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


def main():
    """工具只在显式 test 命令执行插件，其余操作均不导入插件入口"""
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="plugin-sdk")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "package"):
        child = commands.add_parser(command)
        child.add_argument("source", type=Path)
        child.add_argument("--include", action="append", default=[])
        if command == "package":
            child.add_argument("output", type=Path)
    child = commands.add_parser("environment-lock")
    child.add_argument("source", type=Path)
    child.add_argument("wheels", type=Path)
    child.add_argument("output", type=Path)
    child = commands.add_parser("test")
    child.add_argument("package", type=Path, nargs="?")
    child.add_argument("--enable", action="append", default=[])
    child.add_argument("--ocr-result", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            with tempfile.TemporaryDirectory(prefix="plugin-validate-") as temporary:
                result = package_source(args.source, Path(temporary) / "checked.rmp", args.include)
        elif args.command == "package":
            result = package_source(args.source, args.output, args.include)
        elif args.command == "environment-lock":
            result = environment_lock(args.source, args.wheels, args.output)
        elif args.ocr_result:
            document = validate_ocr_document(
                json.loads(args.ocr_result.read_text(encoding="utf-8"))
            )
            result = {
                "valid": True,
                "pages": len(document["pages"]),
                "needs_review": document["needs_review"],
            }
        elif args.package:
            from resume_maker.plugins.testing import test_package

            result = test_package(args.package.resolve(), args.enable)
        else:
            parser.error("test 需要插件包或 --ocr-result")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, PluginError, ProviderError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
