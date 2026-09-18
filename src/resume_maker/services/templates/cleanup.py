"""永久删除模板的受控文件清理；保留其他模板共享的识别产物"""

import json
import shutil
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.integrations.sources import digest


def managed_path(root, path):
    """删除前验证绝对边界和整棵目录中的链接且不允许跳出应用数据目录"""
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
    """读取随模板保存的相对产物索引；兼容尚未登记索引的旧模板"""
    return set(template["mapping"].get("artifacts", []))


def cleanup_template(root, template, others, tasks=None, previews=None):
    """在调用方锁和事务中清理专属文件；再使旧任务失效；失败时保留回收站记录"""
    if tasks and any(thread.is_alive() for thread in tasks.threads):
        raise Problem("正在识别模板，请等待识别完成后再永久删除。", 409)
    shared = set().union(*(artifact_paths(item) for item in others))
    paths = {root / relative for relative in artifact_paths(template) - shared}
    if tasks:
        for key, origin in tasks.origins.items():
            relative = f"workspaces/template-{key}"
            if origin == template["id"] and relative not in shared:
                paths.add(root / relative)
    same_hash = any(item["hash"] == template["hash"] for item in others)
    if not same_hash:
        paths.add(root / "templates" / ".previews" / template["hash"])
        # 旧版本没有产物索引；按内容哈希寻找本应用的原始分析与试填目录
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
    preview_ids = []
    if previews and previews.directory:
        preview_ids = [key for key, value in previews.templates.items() if value == template["id"]]
        paths.update(Path(previews.directory.name) / key for key in preview_ids)
    paths.add(root / "templates" / template["id"])
    # 必须先验证全部目标；再执行首个删除；永久删除过程中失败可在回收站重试
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
        removed = [key for key in tasks.tasks if root / "workspaces" / f"template-{key}" in paths]
        for key in removed:
            tasks.tasks.pop(key, None)
            tasks.started.pop(key, None)
            tasks.flags.pop(key, None)
            tasks.artifacts.pop(key, None)
            tasks.origins.pop(key, None)
    if previews:
        for key in preview_ids:
            previews.results.pop(key, None)
            previews.templates.pop(key, None)
        previews.cache = {
            key: value for key, value in previews.cache.items() if value["id"] not in preview_ids
        }
