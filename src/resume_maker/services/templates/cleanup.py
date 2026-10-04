"""永久删除模板的受控文件清理，保留其他模板共享的识别产物"""

import json
import shutil
from pathlib import Path

from resume_maker.core.content import digest
from resume_maker.core.errors import Problem


def managed_path(root, path):
    """删除前核验绝对路径和目录树中的链接均位于应用数据目录内"""
    root, path = root.resolve(), Path(path).absolute()
    if path == root or not path.resolve().is_relative_to(root):
        raise Problem("模板清理路径超出项目数据目录，已停止删除。", 409)
    for node in [path, *path.parents]:
        if node == root:
            break
        if node.is_symlink() or node.is_junction():
            raise Problem("模板清理目录包含链接，已停止删除。", 409)
    if path.is_dir() and any(p.is_symlink() or p.is_junction() for p in path.rglob("*")):
        raise Problem("模板清理目录包含链接，已停止删除。", 409)
    return path


def artifact_paths(template):
    """读取随模板保存的相对产物索引，兼容尚未登记索引的旧模板"""
    return set(template["mapping"].get("artifacts", []))


def cleanup_template(root, template, others, tasks=None, previews=None, conn=None):
    """在调用方锁和事务中清理专属文件，再使旧任务失效，失败时保留回收站记录"""
    shared = set().union(*(artifact_paths(item) for item in others))
    paths = {root / relative for relative in artifact_paths(template) - shared}
    if tasks:
        paths.update(tasks.cleanup_paths(template["id"], shared))
    same_hash = any(item["hash"] == template["hash"] for item in others)
    if not same_hash:
        paths.add(root / "templates" / ".previews" / template["hash"])
        # 旧版本没有产物索引，按内容哈希寻找本应用的原始分析和试填目录
        for directory in (root / "workspaces").glob("template-*"):
            source = directory / "original.docx"
            if source.is_file() and digest(source.read_bytes()) == template["hash"]:
                if directory.relative_to(root).as_posix() not in shared:
                    paths.add(directory)
    if not any(item["mapping"].get("plan") == template["mapping"].get("plan") for item in others):
        for cache in (root / "template-cache").glob("*.json"):
            try:
                if (
                    cache.relative_to(root).as_posix() not in shared
                    and json.loads(cache.read_text(encoding="utf-8")) == template["mapping"]["plan"]
                ):
                    paths.add(cache)
            except (ValueError, OSError):
                continue
    if previews:
        paths.update(previews.template_artifacts(template["id"]))
    paths.add(root / "templates" / template["id"])
    # 必须先验证全部目标，再执行首个删除，永久删除过程中失败可在回收站重试
    checked = [managed_path(root, path) for path in paths]
    try:
        for path in sorted(checked, key=lambda value: len(value.parts), reverse=True):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
    except OSError as exc:
        raise Problem(
            "部分模板文件正在使用，尚未完成永久删除，请关闭相关文件后重试。", 409
        ) from exc
    if tasks:
        tasks.invalidate_artifacts(conn, paths)
    if previews:
        if conn is None:
            previews.invalidate_template(template["id"])
        else:
            conn.after_commit(lambda: previews.invalidate_template(template["id"]))
