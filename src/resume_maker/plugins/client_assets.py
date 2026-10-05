"""发行代码包独立构建的客户端资源位置和内容摘要"""

import hashlib
from pathlib import Path


def client_directory(identifier: str) -> Path:
    """源码使用任务构建目录，wheel 使用所属插件目录内的客户端产物"""
    slug = identifier.replace(".", "_").replace("-", "_")
    package = Path(__file__).parents[1] / "plugin_packages" / slug
    source = Path(__file__).parents[2]
    if source.name == "src" and (source.parent / "pyproject.toml").is_file():
        return source.parent / ".local" / "plugin-builds" / slug
    return package / "client_dist"


def client_digest(identifier: str) -> str:
    """构建索引摘要标识整套产物，缺构建时由可选客户端报告入口不可用"""
    index = client_directory(identifier) / "artifacts.json"
    return hashlib.sha256(index.read_bytes()).hexdigest() if index.is_file() else "unbuilt"
