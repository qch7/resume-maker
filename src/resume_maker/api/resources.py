"""资源下载期间持有租约，断开或异常同样归还"""

from starlette.responses import FileResponse, Response


class LeasedFileResponse(Response):
    """把临时文件租约延伸到完整 ASGI 传输结束"""

    def __init__(self, lease, filename):
        """延迟获取路径，避免路由返回与实际传输之间被缓存回收"""
        super().__init__()
        self.lease, self.filename = lease, filename

    async def __call__(self, scope, receive, send):
        """传输完成、失败或断开后均归还租约"""
        with self.lease() as path:
            await FileResponse(path, filename=self.filename)(scope, receive, send)


class AssetResponse(Response):
    """响应实际开始后读取资源，关闭前不允许回收"""

    def __init__(self, assets, identifier, filename=None, *, media_type=None, headers=None):
        """仅保留资源引用，路径和摘要由资源服务核验"""
        super().__init__()
        self.assets, self.identifier, self.filename = assets, identifier, filename
        self.file_media_type, self.file_headers = media_type, headers

    async def __call__(self, scope, receive, send):
        """用异常安全的租约覆盖完整 ASGI 文件传输"""
        with self.assets.lease(self.identifier) as path:
            await FileResponse(
                path,
                filename=self.filename,
                media_type=self.file_media_type,
                headers=self.file_headers,
            )(scope, receive, send)
