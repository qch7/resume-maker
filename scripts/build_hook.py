"""将已构建的前端与 Python wheel 一起分发；开发安装不要求预先构建"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """仅在正式 wheel 构建中携带静态资源；保持首次 uv sync 可执行"""

    def initialize(self, version: str, build_data: dict) -> None:
        """校验前端产物并加入 wheel；缺少产物时中止而不生成不可用安装包"""
        if self.target_name != "wheel" or version == "editable":
            return
        frontend = Path(self.root) / "frontend" / "dist"
        if not (frontend / "index.html").is_file():
            raise RuntimeError(
                "请先运行 npm --prefix frontend ci 和 npm --prefix frontend run build。"
            )
        build_data.setdefault("force_include", {})[str(frontend)] = "resume_maker/web"
