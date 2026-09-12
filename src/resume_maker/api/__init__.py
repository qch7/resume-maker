"""HTTP 接口包，对外保留应用工厂入口。"""

from resume_maker.api.app import create_app

__all__ = ["create_app"]
