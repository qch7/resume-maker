"""使用已校验的离线 wheel 锁准备新解释器，活动环境始终保持不变"""

import hashlib
import json
import os
import re
import shutil
import sys
import threading
from pathlib import Path
from uuid import uuid4

from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version

from resume_maker.runtime.graph import PluginError
from resume_maker.runtime.packages import check_dependencies, safe_member
from resume_maker.runtime.state import StateStore, fingerprint


class EnvironmentStore:
    """仅安装二进制 wheel，不下载最新版本、不执行源码构建、不修改现有 venv"""

    def __init__(self, directory, *, records=None):
        """解释器环境独立于资料备份，索引只引用已完成健康检查的环境"""
        self.root = directory / "plugin-environments"
        self.index = directory / "plugin-environments.json"
        self.writer = StateStore(directory)
        self.lock = threading.RLock()
        self.record_override = records

    def records(self):
        """读取明确提交的环境引用，未完成目录不被选用"""
        if self.record_override is not None:
            from copy import deepcopy

            return deepcopy(self.record_override)
        if not self.index.exists():
            return {}
        value = json.loads(self.index.read_text(encoding="utf-8"))
        if value.get("version") != 1:
            raise PluginError("插件环境索引版本不受支持")
        return value["environments"]

    def inspect(self, manifest, location):
        """锁中每个包必须提供名称、精确版本和包内 wheel 摘要"""
        if not manifest.environment_lock:
            raise PluginError("插件没有提供离线环境锁，请由发布者补充全部二进制依赖")
        relative = safe_member(manifest.environment_lock)
        specification = json.loads(location.joinpath(*relative.parts).read_text(encoding="utf-8"))
        if specification.get("version") != 1 or not isinstance(specification.get("wheels"), list):
            raise PluginError("环境锁格式不受支持")
        wheels, versions = [], {}
        for item in specification["wheels"]:
            path = location.joinpath(*safe_member(item["file"]).parts)
            if (
                path.suffix != ".whl"
                or path.is_symlink()
                or not path.resolve().is_relative_to(location)
            ):
                raise PluginError("环境依赖必须是包内普通 wheel 文件")
            name, version, _, _ = parse_wheel_filename(path.name)
            if canonicalize_name(item["name"]) != name or Version(item["version"]) != version:
                raise PluginError("环境锁包名或版本不符合 wheel 文件名")
            if name in versions:
                raise PluginError(f"同一环境存在重复或冲突版本：{name}")
            if (
                not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
            ):
                raise PluginError("环境 wheel 摘要不匹配")
            versions[name] = str(version)
            wheels.append((path, item["sha256"]))
        if missing := check_dependencies(manifest, versions=versions):
            raise PluginError("环境锁缺少声明依赖：" + "; ".join(missing))
        if "host" in manifest.entrypoints and "resume-maker" not in versions:
            raise PluginError("共享 Host 环境锁必须同时包含 Resume Maker 和全部系统依赖")
        return specification, wheels

    def prepare(
        self,
        manifest,
        location,
        execution,
        sandbox,
        host_manifests=(),
        *,
        cancelled=None,
        commit=True,
    ):
        """在独立目录完成环境安装和依赖检查，成功后才发布索引"""
        with self.lock:
            specification, wheels = self.inspect(manifest, location)
            uv = shutil.which("uv")
            if not uv:
                raise PluginError("环境准备需要已安装的 uv，不会自动下载执行程序")
            identifier = str(uuid4())
            target = (self.root / identifier).resolve()
            if target.parent != self.root.resolve() or target.exists():
                raise PluginError("候选环境位置无效")
            target.mkdir(parents=True)
            cancelled = cancelled or threading.Event()
            environment = {
                key: value
                for key, value in os.environ.items()
                if key.upper()
                in {
                    "SYSTEMROOT",
                    "WINDIR",
                    "PATH",
                    "TEMP",
                    "TMP",
                    "USERPROFILE",
                    "HOME",
                    "LOCALAPPDATA",
                }
            }
            operation = {
                "id": identifier,
                "state": "preparing",
                "plugin": manifest.id,
                "package_digest": location.name,
                "lock_digest": fingerprint(specification),
            }
            self.writer.write(target / "operation.json", operation)

            def run(command):
                """每一步安装进程都使用同一系统回收边界和受审查命令"""
                grant = sandbox.authorize(
                    manifest.id,
                    "plugin.environment",
                    1,
                    ["process_cleanup"],
                    command=command,
                    cwd=target,
                    env=environment,
                )
                return execution.execute(
                    grant, command, cwd=target, env=environment, timeout=300, cancelled=cancelled
                )

            try:
                # POSIX 默认使用指向基础解释器的链接，独立环境须持有自己的可核验副本
                run(
                    [
                        sys.executable,
                        "-I",
                        "-m",
                        "venv",
                        "--copies",
                        "--without-pip",
                        str(target / "venv"),
                    ]
                )
                python = (
                    target / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                )
                lockfile = target / "requirements.txt"
                lockfile.write_text(
                    "\n".join(f"{path.as_uri()} --hash=sha256:{digest}" for path, digest in wheels),
                    encoding="utf-8",
                )
                if wheels:
                    run(
                        [
                            uv,
                            "pip",
                            "install",
                            "--offline",
                            "--no-index",
                            "--no-deps",
                            "--require-hashes",
                            "--only-binary=:all:",
                            "--python",
                            str(python),
                            "-r",
                            str(lockfile),
                        ]
                    )
                run([uv, "pip", "check", "--python", str(python)])
                versions = json.loads(
                    run(
                        [
                            str(python),
                            "-I",
                            "-c",
                            "import json,importlib.metadata as m; "
                            "print(json.dumps({d.metadata['Name']:d.version "
                            "for d in m.distributions()}))",
                        ]
                    )
                )
                if missing := check_dependencies(manifest, versions=versions):
                    raise PluginError("候选环境依赖检查失败：" + "; ".join(missing))
                if "host" in manifest.entrypoints:
                    for candidate in host_manifests:
                        if (
                            "worker" in candidate.entrypoints
                            and "host" not in candidate.entrypoints
                        ):
                            continue
                        if missing := check_dependencies(candidate, versions=versions):
                            raise PluginError(
                                f"候选 Host 环境不满足 {candidate.id}：" + "; ".join(missing)
                            )
                record = {
                    **operation,
                    "state": "ready",
                    "python": str(python),
                    "versions": versions,
                    "mode": "host" if "host" in manifest.entrypoints else "worker",
                    "checked_plugins": {item.id: item.version for item in host_manifests}
                    if "host" in manifest.entrypoints
                    else {manifest.id: manifest.version},
                    "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
                }
                self.writer.write(target / "operation.json", record)
                records = self.records()
                records[manifest.id] = record
                if commit:
                    self.writer.write(self.index, {"version": 1, "environments": records})
                return record
            except BaseException as exc:
                self.writer.write(
                    target / "operation.json",
                    {**operation, "state": "failed", "error": type(exc).__name__},
                )
                raise

    def prepare_host(self, candidates, execution, sandbox, host_manifests, *, cancelled=None):
        """合并联合包的固定 wheel 集合，同名不同版本或不同产物立即拒绝"""
        from resume_maker.sdk.manifest import Entry, Manifest

        wheels = {}
        for manifest, location in candidates:
            _, artifacts = self.inspect(manifest, location)
            for path, digest in artifacts:
                name, version, _, _ = parse_wheel_filename(path.name)
                if name in wheels and wheels[name][1:] != (str(version), digest):
                    raise PluginError(f"联合 Host 环境存在固定依赖冲突：{name}")
                wheels[name] = (path, str(version), digest)
        lock = {
            "version": 1,
            "wheels": [
                {"name": name, "version": version, "file": path.name, "sha256": digest}
                for name, (path, version, digest) in sorted(wheels.items())
            ],
        }
        directory = self.root / ("cohort-" + fingerprint(lock))
        directory.mkdir(parents=True, exist_ok=True)
        for path, _, digest in wheels.values():
            if cancelled is not None and cancelled.is_set():
                raise PluginError("联合环境准备已取消")
            target = directory / path.name
            if not target.exists():
                shutil.copyfile(path, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise PluginError("联合环境材料摘要不匹配")
        self.writer.write(directory / "lock.json", lock)
        manifest = Manifest(
            id="host.cohort",
            title="联合宿主环境",
            version="1.0.0",
            package="resume-maker",
            entrypoints={"host": Entry(mode="trusted-host", entry="cohort:activate")},
            environment_lock="lock.json",
        )
        return self.prepare(
            manifest,
            directory,
            execution,
            sandbox,
            host_manifests,
            cancelled=cancelled,
            commit=False,
        )

    def available(self, locations):
        """启动时只选择匹配当前包摘要且解释器完整的已准备环境"""
        result = {}
        for owner, record in self.records().items():
            location = locations.get(owner)
            if location is None or record["package_digest"] != location.name:
                continue
            python = Path(record["python"])
            if not python.resolve().is_relative_to(self.root.resolve()) or not python.is_file():
                raise PluginError("已准备的插件环境不存在或位置无效")
            if hashlib.sha256(python.read_bytes()).hexdigest() != record["python_sha256"]:
                raise PluginError("插件环境解释器发生变化，请重新准备环境")
            if record["mode"] == "worker":
                result[owner] = record
        return result
