"""运行目录、实例令牌和前端资源位置配置"""

import secrets
from dataclasses import dataclass, field
from pathlib import Path

from resume_maker.core.environment import DEFAULT_PORT, LaunchSettings, environment_path
from resume_maker.core.supervisor_policy import SupervisorPolicy


def source_project_directory() -> Path | None:
    """只根据安装源码位置识别项目根目录，不搜索启动目录"""
    source = Path(__file__).resolve().parents[2]
    project = source.parent
    return project if source.name == "src" and (project / "pyproject.toml").is_file() else None


def default_data_directory() -> Path:
    """正式资料默认目录独立于进程环境覆盖"""
    project = source_project_directory()
    return project / "data" if project is not None else Path.home() / ".resume-maker"


def data_directory() -> Path:
    """源码运行默认使用项目 data 目录，安装包回退到用户目录，允许环境变量覆盖"""
    return environment_path("RESUME_MAKER_DATA_DIR") or default_data_directory()


def sandbox_directory() -> Path:
    """源码运行使用项目 .local 沙箱，安装包使用独立用户目录且不跟随启动位置"""
    project = source_project_directory()
    if project is not None:
        return project / ".local" / "sandbox"
    return Path.home() / ".resume-maker-sandbox"


def frontend_directory() -> Path:
    """优先使用显式资源目录，其次使用 wheel 内资源，开发时回退到仓库构建目录"""
    return environment_path("RESUME_MAKER_FRONTEND_DIR") or default_frontend_directory()


def default_frontend_directory() -> Path:
    """优先 wheel 内资源，其次使用源码构建目录，不读取环境覆盖"""
    package = Path(__file__).resolve().parents[1] / "web"
    if (package / "index.html").is_file():
        return package
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


def default_env_file() -> Path | None:
    """源码启动只读取项目根目录 .env，安装包须显式指定配置文件"""
    project = source_project_directory()
    path = project / ".env" if project is not None else None
    return path if path is not None and path.is_file() else None


@dataclass
class Config:
    """运行配置：目录和令牌按实例生成，个人数据目录不纳入 Git"""

    data_dir: Path = field(default_factory=data_directory)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    instance_id: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    port: int = DEFAULT_PORT
    frontend: Path = field(default_factory=frontend_directory)
    profile: str | None = None
    plugins: tuple[str, ...] | None = None
    plugin_config: Path | None = None
    package_root: Path | None = None
    package_records: dict | None = None
    environment_records: dict | None = None
    supervisor: SupervisorPolicy = field(default_factory=SupervisorPolicy)

    def __post_init__(self):
        """程序式应用构造同样验证端口，不接受无效监听范围"""
        self.port = LaunchSettings(port=self.port).port

    def prepare(self) -> None:
        """规范化数据目录并创建工作副本和缓存目录"""
        self.data_dir = self.data_dir.resolve()
        for name in ("workspaces", "templates"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
