"""有界临时预览缓存，文件传输租约阻止正在使用的目录回收"""

import shutil
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from resume_maker.core.errors import Problem

MAX_PREVIEW_ENTRIES = 24
MAX_PREVIEW_BYTES = 128 * 1024 * 1024


class PreviewCache:
    """只清理本实例创建的目录，数量和总字节均受固定资源预算约束"""

    def __init__(
        self, workspace, *, prefix, max_entries=MAX_PREVIEW_ENTRIES, max_bytes=MAX_PREVIEW_BYTES
    ):
        """缓存锁与渲染锁独立，旧页下载无需等待下一次 Word 渲染"""
        self.workspace, self.prefix = Path(workspace), prefix
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.directory = None
        self.entries = OrderedDict()
        self.lock = threading.RLock()

    @contextmanager
    def allocate(self):
        """分配本轮目录，任何未发布或失败的部分产物都立即回收"""
        with self.lock:
            if self.directory is None:
                self.workspace.mkdir(parents=True, exist_ok=True)
                self.directory = TemporaryDirectory(prefix=self.prefix, dir=self.workspace)
            identifier = str(uuid4())
            path = Path(self.directory.name) / identifier
            path.mkdir()
        try:
            yield identifier, path
        finally:
            with self.lock:
                if identifier not in self.entries:
                    self._remove(path)

    def publish(self, identifier, path, files, *, owner=None):
        """登记完整产物并回收最久未使用结果，下载中的文件保持可用"""
        size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        if size > self.max_bytes:
            raise Problem("本次预览超过临时文件容量上限，请减少图片或内容后重试。", 409)
        with self.lock:
            total = sum(entry["size"] for entry in self.entries.values())
            count = len(self.entries)
            victims = []
            for key, entry in self.entries.items():
                if count < self.max_entries and total + size <= self.max_bytes:
                    break
                if not entry["leases"]:
                    victims.append(key)
                    count -= 1
                    total -= entry["size"]
            if count >= self.max_entries or total + size > self.max_bytes:
                raise Problem("预览正在下载，临时容量已满，请等待下载完成后重试。", 409)
            for key in victims:
                self._remove(self.entries.pop(key)["path"])
            self.entries[identifier] = {
                "path": path,
                "size": size,
                "files": set(files),
                "owner": owner,
                "leases": 0,
            }
            return victims

    def touch(self, identifier):
        """缓存命中时更新使用顺序，已回收结果不再复用"""
        with self.lock:
            if identifier not in self.entries:
                return False
            self.entries.move_to_end(identifier)
            return True

    def file(self, identifier, filename, *, owner=None):
        """核对发布清单、归属和存在性，拒绝已失效预览及任意路径"""
        with self.lock:
            entry = self.entries.get(identifier)
            if not entry or (owner is not None and entry["owner"] != owner):
                raise Problem("预览已失效，请重新生成。", 404)
            if filename not in entry["files"]:
                raise Problem("预览文件不存在。", 404)
            path = entry["path"] / filename
            if not path.is_file() or path.is_symlink():
                raise Problem("预览文件已失效，请重新生成。", 404)
            self.entries.move_to_end(identifier)
            return path

    @contextmanager
    def lease(self, identifier, filename, *, owner=None):
        """在完整响应期间持有文件，异常和断开也归还租约"""
        with self.lock:
            path = self.file(identifier, filename, owner=owner)
            entry = self.entries[identifier]
            entry["leases"] += 1
        try:
            yield path
        finally:
            with self.lock:
                entry["leases"] -= 1

    def artifacts(self, owner):
        """维护操作只有在相关下载结束后才能处理对应目录"""
        with self.lock:
            entries = [entry for entry in self.entries.values() if entry["owner"] == owner]
            if any(entry["leases"] for entry in entries):
                raise Problem("该模板的预览正在下载，请稍后重试。", 409)
            return [entry["path"] for entry in entries]

    def discard(self, owner):
        """撤销已清理模板的结果，并清理仍在本缓存中的目录"""
        with self.lock:
            self.artifacts(owner)
            for key in list(self.entries):
                if self.entries[key]["owner"] == owner:
                    self._remove(self.entries.pop(key)["path"])

    def stop(self):
        """请求排空后清理本实例目录，不触碰正式导出或导入原件"""
        with self.lock:
            if any(entry["leases"] for entry in self.entries.values()):
                raise Problem("预览下载尚未结束，请稍后关闭。", 409)
            self.entries.clear()
            if self.directory:
                self.directory.cleanup()
                self.directory = None

    def _remove(self, path):
        """仅删除缓存根下由本实例分配的直接子目录，拒绝链接"""
        root = Path(self.directory.name).resolve()
        if path.parent.resolve() != root or path.is_symlink() or path.resolve().parent != root:
            raise Problem("预览目录边界已变化，保留文件等待处理。", 409)
        if path.exists():
            shutil.rmtree(path)
