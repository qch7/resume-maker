"""运行目录、实例令牌和前端资源位置配置。"""

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def frontend_directory() -> Path:
    """优先使用显式资源目录，其次使用 wheel 内资源，开发时回退到仓库构建目录。"""
    if override := os.environ.get("RESUME_MAKER_FRONTEND_DIR"):
        return Path(override).expanduser().resolve()
    package = Path(__file__).resolve().parents[1] / "web"
    if (package / "index.html").is_file():
        return package
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


@dataclass
class Config:
    """运行配置：目录与令牌按实例生成，个人数据不进入源码仓库。"""

    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("RESUME_MAKER_DATA_DIR", Path.home() / ".resume-maker")
        )
    )
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    instance_id: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    port: int = 8765
    frontend: Path = field(default_factory=frontend_directory)

    def prepare(self) -> None:
        """规范化数据目录并创建快照、模板、导出等运行资源目录。"""
        self.data_dir = self.data_dir.resolve()
        for name in ("snapshots", "workspaces", "templates", "exports", "backups"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
