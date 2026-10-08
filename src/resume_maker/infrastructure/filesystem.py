"""本实例暂存目录的原子发布，兼容 Windows 短暂的文件扫描占用"""

import shutil
import time

_RETRY_ATTEMPTS = 7
_RETRY_BASE_SECONDS = 0.025
_WINDOWS_FILE_LOCK_ERRORS = frozenset({5, 32, 33})


def replace_file(source, target):
    """原子替换保留旧文件，Windows 短暂读取和扫描占用仅有限重试"""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return source.replace(target)
        except PermissionError as exc:
            if (
                getattr(exc, "winerror", None) not in _WINDOWS_FILE_LOCK_ERRORS
                or attempt == _RETRY_ATTEMPTS - 1
            ):
                raise
            time.sleep(_RETRY_BASE_SECONDS * 2**attempt)


def publish_directory(source, target):
    """仅重试短暂共享冲突，目标已出现或永久错误时保留原目录并报错"""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return source.rename(target)
        except PermissionError as exc:
            if (
                getattr(exc, "winerror", None) not in _WINDOWS_FILE_LOCK_ERRORS
                or target.exists()
                or attempt == _RETRY_ATTEMPTS - 1
            ):
                raise
            time.sleep(_RETRY_BASE_SECONDS * 2**attempt)


def remove_owned_directory(root, target):
    """只删除已核验的归属子目录，短暂共享冲突重试后仍失败则保留清理责任"""
    resolved = target.resolve()
    boundary = root.resolve()
    if (
        resolved == boundary
        or not resolved.is_relative_to(boundary)
        or target.is_symlink()
        or target.is_junction()
    ):
        raise ValueError("待清理目录不属于当前资源范围")
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            shutil.rmtree(target)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            if (
                getattr(exc, "winerror", None) not in _WINDOWS_FILE_LOCK_ERRORS
                or attempt == _RETRY_ATTEMPTS - 1
            ):
                raise
            time.sleep(_RETRY_BASE_SECONDS * 2**attempt)
