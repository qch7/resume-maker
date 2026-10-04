"""不可变资源公共契约，业务记录和文件引用在同一事务发布"""

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol


class Assets(Protocol):
    """真实目录及回收实现属于提供方，消费者使用逻辑键和有期限的租约"""

    def stage(self, owner: str, data: bytes, media_type: str) -> dict:
        """暂存完整字节，失败不发布业务引用"""
        ...

    def stage_bundle(self, owner: str, files: dict[str, bytes]) -> dict:
        """暂存完整文件集合，同一集合内相同内容共用原件"""
        ...

    def bundle(self, key: str, conn=None) -> dict | None:
        """在当前快照读取不可变文件集合的索引"""
        ...

    def publish_bundle(self, conn, owner: str, key: str, staged: dict) -> dict:
        """替换完整集合，引用转移和业务写入原子提交"""
        ...

    def update_bundle(self, conn, owner: str, key: str, staged: dict) -> dict:
        """只更新明确提供的文件，其余文件保留"""
        ...

    def release_bundle(self, conn, owner: str, key: str) -> None:
        """同事务解除索引和全部引用，文件仍等待显式维护回收"""
        ...

    def file_id(self, key: str, name: str) -> str:
        """按逻辑文件查找资源标识，不暴露真实磁盘路径"""
        ...

    def lease(self, identifier: str) -> AbstractContextManager[Path]:
        """核验不可变原件并保持租约，直到读取或下载实际结束"""
        ...

    def open_file(self, key: str, name: str) -> AbstractContextManager[Path]:
        """取得业务逻辑文件的短期只读租约"""
        ...

    def read_file(self, key: str, name: str) -> bytes:
        """在租约内读取完整原件，返回与存储独立的字节"""
        ...
