"""本机服务启动和离线恢复的命令行入口"""

import argparse
import json
import os
import socket
import threading
import webbrowser
from pathlib import Path
from typing import get_args

import uvicorn
from pydantic import ValidationError

from resume_maker.core.config import (
    Config,
    default_data_directory,
    default_env_file,
    default_frontend_directory,
)
from resume_maker.core.environment import LaunchProfile, LaunchSettings, resolve_launch
from resume_maker.core.errors import Problem
from resume_maker.infrastructure.storage import instance_lock, restore_backup
from resume_maker.runtime.graph import PluginError

from .api import create_app


def add_launch_arguments(parser):
    """所有官方启动器复用相同参数、配置文件开关和布尔覆盖语义"""
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--frontend-dir", type=Path, help="覆盖前端静态资源目录")
    browser = parser.add_mutually_exclusive_group()
    browser.add_argument("--no-browser", dest="open_browser", action="store_false")
    browser.add_argument("--browser", dest="open_browser", action="store_true")
    parser.set_defaults(open_browser=None)
    parser.add_argument("--profile", choices=get_args(LaunchProfile))
    parser.add_argument("--plugin-config", type=Path, help="插件默认组合及本次启动覆盖 JSON")
    file = parser.add_mutually_exclusive_group()
    file.add_argument("--env-file", type=Path, help="读取指定的 UTF-8 启动配置文件")
    file.add_argument("--no-env-file", action="store_true", help="关闭源码根目录 .env 自动读取")
    parser.add_argument("--print-config", action="store_true", help="输出有效启动配置及来源后退出")


def configured_launch(args):
    """在任何资料读写前解析配置，同时为监督器固定当前有效覆盖"""
    overrides = {
        name: getattr(args, name)
        for name in LaunchSettings.model_fields
        if getattr(args, name) is not None
    }
    env_file = None if args.no_env_file else args.env_file or default_env_file()
    resolved = resolve_launch(env_file=env_file, overrides=overrides)
    settings = resolved.settings
    config = Config(
        port=settings.port,
        data_dir=settings.data_dir or default_data_directory(),
        frontend=settings.frontend_dir or default_frontend_directory(),
        profile=settings.profile,
        plugin_config=settings.plugin_config,
    )
    args.port = config.port
    args.data_dir = config.data_dir
    args.no_browser = not settings.open_browser
    args.profile = settings.profile
    args.plugin_config = settings.plugin_config
    args.frontend_dir = settings.frontend_dir
    return config, resolved


def main(argv=None):
    """解析命令行，持有实例锁后启动本机服务，或执行离线备份恢复"""
    parser = argparse.ArgumentParser(description="Resume Maker 本地工作台")
    add_launch_arguments(parser)
    parser.add_argument("--host-child", action="store_true", help=argparse.SUPPRESS)
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
    args = parser.parse_args(argv)
    try:
        config, resolved = configured_launch(args)
        if args.print_config:
            print(
                json.dumps(
                    resolved.public_values(data_dir=config.data_dir, frontend=config.frontend)
                )
            )
            return
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
    except (Problem, PluginError, OSError, ValueError, ValidationError) as exc:
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
