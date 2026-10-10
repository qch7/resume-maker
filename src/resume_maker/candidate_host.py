"""由已授权监督调用的独立候选宿主，不提供 HTTP 监听或真实模型任务"""

import json
import sys
import time
from pathlib import Path

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.runtime.graph import PluginError


def main():
    """试运行完整候选组合，任何缺失能力、健康失败和清理失败均返回失败"""
    specification = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    config = Config(
        data_dir=Path(specification["data_dir"]),
        package_root=Path(specification["package_root"]),
        package_records=specification["packages"],
        environment_records=specification["environments"],
    )
    app = create_app(config)
    host = app.state.runtime
    try:
        if host.selected != set(specification["selected"]) or host.blocked:
            raise PluginError("候选组合存在缺失或不兼容能力")
        host.start()
        host.check_health()
        time.sleep(0.2)
        host.check_health()
    finally:
        host.close()


if __name__ == "__main__":
    main()
