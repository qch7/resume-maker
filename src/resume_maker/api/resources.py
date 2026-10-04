"""资源下载期间持有租约，断开或异常同样归还"""

from starlette.responses import FileResponse, Response


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
