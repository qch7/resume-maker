"""本机服务启动和离线恢复的命令行入口"""

import argparse
import json
import os
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from resume_maker.core.config import Config
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.storage import instance_lock, restore_backup
from resume_maker.runtime.graph import PluginError

from .api import create_app


def main():
    """解析命令行，持有实例锁后启动本机服务，或执行离线备份恢复"""
    parser = argparse.ArgumentParser(description="Resume Maker 本地工作台")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--host-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile", choices=("minimal", "standard"))
    parser.add_argument("--plugin-config", type=Path, help="插件默认组合及本次启动覆盖 JSON")
    parser.add_argument("--restore", type=Path, metavar="BACKUP_ZIP", help="离线恢复备份后退出")
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument(
        "--plugin-data-plan", metavar="PLUGIN_ID", help="停机生成插件资料迁移计划"
    )
    maintenance.add_argument(
        "--plugin-data-apply", type=Path, metavar="PLAN_JSON", help="停机应用已审查的数据迁移计划"
    )
    maintenance.add_argument(
        "--asset-gc-plan", action="store_true", help="停机生成失败暂存和墓碑资源回收计划"
    )
    maintenance.add_argument(
        "--asset-gc-apply", type=Path, metavar="PLAN_JSON", help="停机应用已审查的资源回收计划"
    )
    parser.add_argument("--confirm-digest", help="确认迁移计划的完整摘要")
    args = parser.parse_args()
    config = Config(port=args.port, profile=args.profile, plugin_config=args.plugin_config)
    if args.data_dir:
        config.data_dir = args.data_dir.resolve()
    try:
        if args.asset_gc_plan or args.asset_gc_apply:
            with instance_lock(config.data_dir):
                maintain_assets(config, args)
            return
        if args.plugin_data_plan or args.plugin_data_apply:
            with instance_lock(config.data_dir):
                maintain_plugin(config, args)
            return
        if args.restore:
            previous = restore_backup(args.restore, config.data_dir)
            print(f"已恢复到 {config.data_dir}")
            if previous:
                print(f"恢复前的数据保存在 {previous}")
            return
        if not args.host_child:
            from resume_maker.host_supervisor import supervise

            supervise(config, args)
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
                uvicorn.Config(
                    app, host="127.0.0.1", port=args.port, log_level="error", access_log=False
                )
            )
            app.state.stop_server = lambda: setattr(server, "should_exit", True)
            from resume_maker.host_supervisor import watch_host

            stopped = watch_host(app, config, server)
            try:
                server.run()
            finally:
                stopped.set()
    except (Problem, PluginError, OSError, ValidationError) as exc:
        parser.error(str(exc))


def maintain_assets(config, args):
    """停机回收只处理已审查的资源，不装载外部插件和业务代码"""
    from resume_maker.infrastructure.assets import Assets
    from resume_maker.infrastructure.database import Database

    assets = Assets(Database(config.data_dir / "resume.db"), config.data_dir)
    if args.asset_gc_apply:
        plan = json.loads(args.asset_gc_apply.read_text(encoding="utf-8"))
        if not args.confirm_digest or args.confirm_digest != plan.get("digest"):
            raise Problem("请检查计划后通过 --confirm-digest 确认完整摘要。", 409)
        print(json.dumps(assets.collect(plan), ensure_ascii=False, indent=2))
    else:
        plan = assets.collection_plan()
        path = config.data_dir / "backups" / "asset-gc-plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"plan": str(path), **plan}, ensure_ascii=False, indent=2))


def maintain_plugin(config, args):
    """可信停机维护入口读取安装包，备份从不携带可执行迁移"""
    from resume_maker.infrastructure.data_maintenance import DataMaintenance
    from resume_maker.infrastructure.database import Database
    from resume_maker.plugins.discovery import discover
    from resume_maker.runtime.packages import PackageStore

    approved = (
        json.loads(args.plugin_data_apply.read_text(encoding="utf-8"))
        if args.plugin_data_apply
        else None
    )
    owner = approved["owner"] if approved else args.plugin_data_plan
    packages = PackageStore(config.data_dir, set(discover()[0]))
    manifests, locations = packages.discover()
    if owner not in manifests:
        raise Problem("迁移需要已安装并通过摘要校验的外部插件。", 409)
    coordinator = DataMaintenance(Database(config.data_dir / "resume.db"), config.data_dir)
    if approved:
        if not args.confirm_digest or args.confirm_digest != approved.get("digest"):
            raise Problem("请检查计划后通过 --confirm-digest 确认完整摘要。", 409)
        result = coordinator.apply(approved, manifests[owner], locations[owner])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        plan = coordinator.plan(manifests[owner], locations[owner])
        path = config.data_dir / "backups" / "migrations" / f"plan-{owner}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"plan": str(path), **plan}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
