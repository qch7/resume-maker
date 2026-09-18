"""在仓库外验证 wheel 的导入、数据库与静态资源"""

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
    """在临时目录验证最新 wheel；隔离个人数据与源码导入"""
    wheels = sorted((ROOT / "dist").glob("*.whl"), key=modified_at)
    if not wheels:
        raise SystemExit("请先运行 uv build --wheel。")
    with tempfile.TemporaryDirectory(prefix="resume-maker-wheel-") as temporary:
        target = Path(temporary)
        with ZipFile(wheels[-1]) as archive:
            archive.extractall(target / "package")
        # 仅把已解包安装包放到导入路径首位；保留当前虚拟环境提供第三方运行依赖
        script = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "package"))
from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.infrastructure.database import SCHEMA_VERSION
from resume_maker.services.templates.analysis import INSTRUCTIONS
assert "name: resume-template-mapping" in INSTRUCTIONS
config = Config(data_dir=Path.cwd() / "data")
assert config.frontend == (Path.cwd() / "package/resume_maker/web").resolve(), config.frontend
assert (config.frontend / "index.html").is_file()
assert list((config.frontend / "assets").glob("*.js"))
app = create_app(config)
assert app.state.services.db.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
assert "/api/state" in app.openapi()["paths"]
print("Wheel 验证通过：应用可导入，静态资源和数据库初始结构完整。")
"""
        # 隔离模式会忽略 PYTHONUTF8；必须通过解释器参数保留中文日志的编码约定
        subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", script], cwd=target, check=True)


if __name__ == "__main__":
    main()
