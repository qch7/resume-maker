"""在仓库外验证 wheel 的导入、数据库和静态资源"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

from resume_maker.core.process_environment import EnvironmentPolicy, process_environment

ROOT = Path(__file__).resolve().parents[1]


def modified_at(path: Path) -> float:
    """按产物的修改时间挑选最近构建的 wheel"""
    return path.stat().st_mtime


def main() -> None:
    """在临时目录验证最新 wheel，隔离个人数据和源码导入"""
    wheels = sorted((ROOT / ".local" / "artifacts").glob("*.whl"), key=modified_at)
    if not wheels:
        raise SystemExit("请先运行 uv build --wheel --out-dir .local/artifacts。")
    with tempfile.TemporaryDirectory(prefix="resume-maker-wheel-") as temporary:
        target = Path(temporary)
        with ZipFile(wheels[-1]) as archive:
            assert not any(
                part == ".env" or part.startswith(".env.")
                for name in archive.namelist()
                for part in Path(name).parts
            ), "wheel 不应包含本机环境配置"
            archive.extractall(target / "package")
        # 仅把已解包安装包放到导入路径首位，保留当前虚拟环境提供第三方运行依赖
        script = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "package"))
from resume_maker.api import create_app
from resume_maker.core.config import Config, sandbox_directory
from resume_maker.infrastructure.database import SCHEMA_VERSION
from resume_maker.plugin_packages.ext_template_ai.services.templates.analysis import INSTRUCTIONS
from resume_maker.plugin_packages.provider_rapidocr import local_ocr
from resume_maker.integrations.providers import material_server
from resume_maker.integrations.providers.source_broker import source_broker
from resume_maker.integrations.source_access import SourceAccess
from resume_maker.integrations.privacy import Redactor
import json
import threading
assert "name: resume-template-mapping" in INSTRUCTIONS
assert Path(material_server.__file__).is_relative_to(Path.cwd() / "package")
assert sandbox_directory() == Path.home() / ".resume-maker-sandbox"
assert len(material_server.TOOLS) == 2
assert len(material_server.SOURCE_TOOLS) == 3
source = Path.cwd() / "synthetic-source"
source.mkdir()
(source / "main.py").write_text("print('合成身份')", encoding="utf-8")
with SourceAccess([{"id": "source-0", "path": str(source)}], Path.cwd() / "data",
                  Redactor(["合成身份"]), threading.Event()) as access:
    with source_broker(access) as endpoint:
        result = material_server.source_call(endpoint, "read_source",
                                             {"source": "source-0", "path": "main.py"})
        assert "合成身份" not in result and "[[RM_" in result
        restored = access.redactor.restore(json.loads(result))
        assert restored["lines"][0]["text"] == "print('合成身份')"
assert local_ocr.engine() is not None
config = Config(data_dir=Path.cwd() / "data")
assert config.frontend == (Path.cwd() / "package/resume_maker/web").resolve(), config.frontend
assert (config.frontend / "index.html").is_file()
assert list((config.frontend / "assets").glob("*.js"))
from resume_maker.plugins.discovery import discover
from resume_maker.plugins.client_assets import client_directory
import hashlib
definitions, _, _ = discover()
for identifier, manifest in definitions.items():
    if "client" not in manifest.entrypoints:
        continue
    directory = client_directory(identifier)
    index = json.loads((directory / "artifacts.json").read_text(encoding="utf-8"))
    assert "plugin.js" in index
    for name, checksum in index.items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == checksum
assert (config.frontend / "shared/sdk/shared/components/TemplatePicker.js").is_file()
app = create_app(config)
assert app.state.services.db.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
assert "/api/state" in app.openapi()["paths"]
assert app.state.services.recruitment.get()["data"]["bookmarks"] == []
recruitment_resources = Path.cwd() / "package/resume_maker/resources/recruitment"
for name in ["internet", "technology"]:
    assert not (recruitment_resources / f"{name}.bookmarks.json").exists()
print("Wheel 验证通过：应用、静态资源、数据库、只读材料服务和本地 OCR 模型完整。")
"""
        # 隔离模式忽略 PYTHONUTF8，因此通过解释器参数启用 UTF-8
        isolated = process_environment(EnvironmentPolicy.CANDIDATE)
        subprocess.run(
            [sys.executable, "-I", "-X", "utf8", "-c", script],
            cwd=target,
            check=True,
            env=isolated,
        )
        uv = shutil.which("uv")
        if not uv:
            raise SystemExit("物理最小安装验收需要 uv。")
        environment = target / "minimal-environment"
        subprocess.run([uv, "venv", "--python", sys.executable, str(environment)], check=True)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [uv, "pip", "install", "--python", str(python), "--only-binary=:all:", str(wheels[-1])],
            cwd=target,
            check=True,
        )
        subprocess.run(
            [str(python), "-I", "-X", "utf8", str(ROOT / "scripts/wheel_minimal.py")],
            cwd=target,
            check=True,
            env=isolated,
        )
        source = target / "independent-notes-plugin"
        shutil.copytree(ROOT / "docs/examples/notes-plugin", source)
        script = target / "wheel_plugin_author.py"
        shutil.copy2(ROOT / "scripts/wheel_plugin_author.py", script)
        subprocess.run(
            [str(python), "-I", "-X", "utf8", str(script), str(source)],
            cwd=target,
            check=True,
            env=isolated,
        )
        source = target / "independent-ocr-plugin"
        shutil.copytree(ROOT / "docs/examples/ocr-plugin", source)
        package = target / "independent-ocr.rmp"
        for arguments in (
            ["validate", str(source)],
            ["package", str(source), str(package)],
            ["test", str(package), "--enable", "ext.ocr"],
        ):
            subprocess.run(
                [str(python), "-I", "-X", "utf8", "-m", "resume_maker.plugins.tools", *arguments],
                cwd=target,
                check=True,
                env=isolated,
            )


if __name__ == "__main__":
    main()
