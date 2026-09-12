"""本机服务启动与离线恢复的命令行入口。"""

import argparse
import json
import os
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn

from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.storage import instance_lock, restore_backup

from .api import create_app


def main():
    """解析命令行，持有实例锁后启动本机服务，或执行离线备份恢复。"""
    parser = argparse.ArgumentParser(description="Resume Maker 本地工作台")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--restore", type=Path, metavar="BACKUP_ZIP", help="离线恢复备份后退出")
    args = parser.parse_args()
    config = Config(port=args.port)
    if args.data_dir:
        config.data_dir = args.data_dir.resolve()
    try:
        if args.restore:
            previous = restore_backup(args.restore, config.data_dir)
            print(f"已恢复到 {config.data_dir}")
            if previous:
                print(f"恢复前的数据保存在 {previous}")
            return
        with instance_lock(config.data_dir):
            config.prepare()
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", args.port)) == 0:
                    parser.error(f"端口 {args.port} 正在使用，请指定其他 --port。")
            app = create_app(config)
            (config.data_dir / "instance.json").write_text(
                json.dumps(
                    {"pid": os.getpid(), "port": args.port, "instance_id": config.instance_id}
                ),
                encoding="utf-8",
            )
            if not args.no_browser:
                threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="info")
            )
            app.state.stop_server = lambda: setattr(server, "should_exit", True)
            server.run()
    except (Problem, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
