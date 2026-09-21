"""在仓库外验证 wheel 的导入、数据库和静态资源"""

import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def modified_at(path: Path) -> float:
    """按产物的修改时间挑选最近构建的 wheel"""
    return path.stat().st_mtime


def main() -> None:
    """在临时目录验证最新 wheel，隔离个人数据和源码导入"""
    wheels = sorted((ROOT / "dist").glob("*.whl"), key=modified_at)
    if not wheels:
        raise SystemExit("请先运行 uv build --wheel。")
    with tempfile.TemporaryDirectory(prefix="resume-maker-wheel-") as temporary:
        target = Path(temporary)
        with ZipFile(wheels[-1]) as archive:
            archive.extractall(target / "package")
        # 仅把已解包安装包放到导入路径首位，保留当前虚拟环境提供第三方运行依赖
        script = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "package"))
from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.infrastructure.database import SCHEMA_VERSION
from resume_maker.services.templates.analysis import INSTRUCTIONS
from resume_maker.integrations import local_ocr
from resume_maker.integrations.providers import material_server
from resume_maker.integrations.providers.source_broker import source_broker
from resume_maker.integrations.source_access import SourceAccess
from resume_maker.integrations.privacy import Redactor
import json
import threading
assert "name: resume-template-mapping" in INSTRUCTIONS
assert Path(material_server.__file__).is_relative_to(Path.cwd() / "package")
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
app = create_app(config)
assert app.state.services.db.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
assert "/api/state" in app.openapi()["paths"]
print("Wheel 验证通过：应用、静态资源、数据库、只读材料服务和本地 OCR 模型完整。")
"""
        # 隔离模式忽略 PYTHONUTF8，因此通过解释器参数启用 UTF-8
        subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", script], cwd=target, check=True)


if __name__ == "__main__":
    main()
