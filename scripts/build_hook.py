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
        packages = Path(self.root) / "src/resume_maker/plugin_packages"
        for path in packages.glob("*/package.json"):
            import json

            metadata = json.loads(path.read_text(encoding="utf-8"))
            if not metadata["resumeMaker"].get("client"):
                continue
            output = Path(self.root) / ".local/plugin-builds" / path.parent.name
            if not (output / "artifacts.json").is_file():
                raise RuntimeError(f"插件 {path.parent.name} 尚未构建，请重新运行前端构建。")
            build_data["force_include"][str(output)] = (
                f"resume_maker/plugin_packages/{path.parent.name}/client_dist"
            )
