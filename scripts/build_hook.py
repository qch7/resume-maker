"""在 Python wheel 中分发已构建的前端"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """仅正式 wheel 构建携带静态资源"""

    def initialize(self, version: str, build_data: dict) -> None:
        """校验前端产物后将其加入 wheel"""
        if self.target_name != "wheel" or version == "editable":
            return
        frontend = Path(self.root) / "frontend" / "dist"
        if not (frontend / "index.html").is_file():
            raise RuntimeError(
                "请先运行 npm --prefix frontend ci 和 npm --prefix frontend run build。"
            )
        build_data.setdefault("force_include", {})[str(frontend)] = "resume_maker/web"
