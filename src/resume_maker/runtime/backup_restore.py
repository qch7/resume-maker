"""显式备份恢复复用窗口确认，监督器停机后切换资料目录"""

import json
import tempfile
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.backup_history import backup_digest, backup_path, backup_record
from resume_maker.infrastructure.filesystem import publish_directory
from resume_maker.infrastructure.storage import create_backup, instance_lock, restore_backup
from resume_maker.runtime.state import StateStore, fingerprint

LOCAL_RUNTIME = (
    "backups",
    "plugin-packages",
    "plugin-packages.json",
    "plugin-environments",
    "plugin-environments.json",
    "plugin-pins.json",
    "host-runtime.json",
    "host-restore.json",
)


def plan_restore(manager, identifier, generation):
    """恢复固定目标 ZIP，全部窗口保存及任务排空后才允许执行"""
    with manager.lock:
        if (
            manager.pending_plan
            or manager.maintenance
            or any(
                item.get("restore_backup") and item["state"] in {"planned", "preparing"}
                for item in manager.plans.values()
            )
        ):
            raise Problem("请先完成当前资料或插件变更。", 409)
        if not manager.host.bootstrap.get("request_restart"):
            raise Problem("一键恢复需要通过 Resume Maker 官方启动器运行。", 409)
        directory = manager.host.bootstrap["config"].data_dir
        archive = backup_path(directory, identifier)
        if not backup_record(archive)["restorable"]:
            raise Problem("备份清单损坏或格式不受支持，无法恢复。", 409)
        plan = manager.plan(sorted(manager.host.selected), generation)
        plan.update(
            mode="backup-restore",
            affected=sorted(manager.host.selected),
            restore_backup={"id": identifier, "sha256": backup_digest(archive)},
        )
        plan["digest"] = fingerprint({key: value for key, value in plan.items() if key != "digest"})
        manager.plans[plan["id"]] = plan
        manager.save_plan(plan)
        return plan


def start_restore(manager, plan):
    """停机前校验完整备份并保存当前资料，失败解除准备冻结"""
    directory = manager.host.bootstrap["config"].data_dir
    try:
        archive = backup_path(directory, plan["restore_backup"]["id"])
        if backup_digest(archive) != plan["restore_backup"]["sha256"]:
            raise Problem("备份已变化，请重新选择并确认恢复。", 409)
        with tempfile.TemporaryDirectory(
            prefix="restore-check-", dir=directory / "backups"
        ) as root:
            restore_backup(archive, Path(root) / "data")
        backup = create_backup(
            manager.host.services["db"], directory, kind="automatic", reason="before-restore"
        )
        record = {
            "version": 1,
            "id": plan["id"],
            "state": "prepared",
            "archive": archive.name,
            "sha256": plan["restore_backup"]["sha256"],
            "backup": str(backup),
            "plan": {**plan, "state": "restart-required"},
            "previous": str(
                directory.with_name(directory.name + "-before-restore-" + plan["id"][:8])
            ),
        }
        record["digest"] = restore_digest(record)
        manager.save_plan(record["plan"])
        StateStore(directory).write(directory / "host-restore.json", record)
    except Exception:
        manager.abort(plan["id"], plan["digest"])
        raise
    plan.update(state="restart-required")
    manager.maintenance = True
    manager.host.bootstrap["request_restart"]()
    return {"id": plan["id"], "state": "restart-required"}


def restore_digest(record):
    """动态执行阶段不改变用户确认的文件及计划摘要"""
    return fingerprint(
        {
            key: record[key]
            for key in ("version", "id", "archive", "sha256", "backup", "plan", "previous")
        }
    )


def read_restore(directory):
    """监督器只执行已确认且内容未变的本机恢复记录"""
    path = directory / "host-restore.json"
    if not path.is_file():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("version") != 1 or record.get("digest") != restore_digest(record):
        raise Problem("备份恢复记录摘要不匹配，请检查本机维护记录。", 409)
    return record


def save_restore(directory, record, state, message):
    """实际阶段落盘，失败及重启不会自动重复用户的恢复操作"""
    record.update(state=state, message=message)
    writer = StateStore(directory)
    writer.write(directory / "host-restore.json", record)
    writer.save_plan({**record["plan"], "state": state, "message": message})


def apply_restore(directory, record):
    """旧宿主释放实例锁后恢复资料，历史及已安装运行环境继续保留"""
    try:
        archive = backup_path(directory, record["archive"])
        if backup_digest(archive) != record["sha256"]:
            raise Problem("目标备份已变化，已取消恢复。", 409)
        save_restore(directory, record, "applying", "正在停机恢复资料。")
        restore_backup(
            archive,
            directory,
            preserve_local=LOCAL_RUNTIME,
            previous_directory=Path(record["previous"]),
        )
    except Exception as exc:
        save_restore(directory, record, "failed", "恢复失败，原资料已保留：" + str(exc))
        return False
    try:
        # 插件代次必须前进，另一窗口的旧请求不能写入已恢复资料
        writer = StateStore(directory)
        configuration = writer.read()
        if configuration:
            configuration["generation"] = (
                max(configuration["generation"], record["plan"]["generation"]) + 1
            )
            writer.write(writer.path, configuration)
        else:
            writer.commit(
                record["plan"]["selected"],
                record["plan"]["generation"] + 1,
                {},
                record["plan"]["configs"],
                instances=record["plan"]["instances"],
                config_layers=record["plan"]["configuration"]["layers"],
            )
        save_restore(directory, record, "booting", "资料已恢复，正在重新启动服务。")
    except Exception as exc:
        rollback_restore(directory, record, "恢复后的配置发布失败，已回到原资料：" + str(exc))
        return False
    return True


def recover_missing_directory(directory):
    """目录切换被中断且目标缺失时，从已确认的原目录恢复"""
    if directory.exists():
        return
    candidates = []
    for previous in directory.parent.glob(directory.name + "-before-restore-*"):
        if not previous.is_dir() or previous.is_symlink() or previous.is_junction():
            continue
        record = read_restore(previous)
        if record and record["state"] == "applying" and record["previous"] == str(previous):
            candidates.append((previous, record))
    if len(candidates) > 1:
        raise Problem("存在多个中断恢复目录，请核对恢复前资料位置。", 409)
    if candidates:
        previous, record = candidates[0]
        with instance_lock(directory):
            publish_directory(previous, directory)
            save_restore(directory, record, "failed", "上次目录切换中断，已回到恢复前资料。")


def rollback_restore(directory, record, message):
    """恢复后的宿主无法启动时保留故障目录并完整回到恢复前资料"""
    previous = Path(record["previous"])
    if (
        previous.parent != directory.parent
        or not previous.name.startswith(directory.name + "-before-restore-")
        or not previous.is_dir()
        or previous.is_symlink()
        or previous.is_junction()
    ):
        raise Problem("恢复前目录不可用，请从恢复前自动备份恢复资料。", 409)
    failed = directory.with_name(directory.name + "-failed-restore-" + record["id"][:8])
    with instance_lock(directory):
        publish_directory(directory, failed)
        try:
            publish_directory(previous, directory)
        except OSError:
            publish_directory(failed, directory)
            raise
        record["failed_directory"] = str(failed)
        save_restore(directory, record, "failed", message)
