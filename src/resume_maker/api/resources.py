"""资源下载期间持有租约，断开或异常同样归还"""

import anyio
from starlette.responses import FileResponse, Response


class LeasedFileResponse(Response):
    """把临时文件租约延伸到完整 ASGI 传输结束"""

    def __init__(self, lease, filename):
        """延迟获取路径，避免路由返回、实际传输之间被缓存回收"""
        super().__init__()
        self.lease, self.filename = lease, filename

    async def __call__(self, scope, receive, send):
        """传输完成、失败或断开后均归还租约"""
        with self.lease() as path:
            await FileResponse(path, filename=self.filename)(scope, receive, send)


class AssetResponse(Response):
    """响应实际开始后读取资源，关闭前不允许回收"""

    def __init__(self, assets, identifier, filename=None, *, media_type=None, headers=None):
        """仅保留资源引用，路径、摘要由资源服务核验"""
        super().__init__()
        self.assets, self.identifier, self.filename = assets, identifier, filename
        self.file_media_type, self.file_headers = media_type, headers

    async def __call__(self, scope, receive, send):
        """在工作线程校验资源，取消后等待校验及租约收尾，不阻塞事件循环"""
        failure = None

        async def transfer():
            """子任务持有实际线程的生命周期，获取租约后再次检查请求取消"""
            nonlocal failure
            entered = False
            try:
                await anyio.lowlevel.checkpoint()
                lease = self.assets.lease(self.identifier)
                with anyio.CancelScope(shield=True):
                    path = await anyio.to_thread.run_sync(lease.__enter__)
                    entered = True
                await anyio.lowlevel.checkpoint()
                await FileResponse(
                    path,
                    filename=self.filename,
                    media_type=self.file_media_type,
                    headers=self.file_headers,
                )(scope, receive, send)
            except BaseException as exc:
                failure = exc
            finally:
                if entered:
                    # 归还不争用下载线程额度，父请求取消也不能跳过租约释放
                    with anyio.CancelScope(shield=True):
                        try:
                            suppressed = await anyio.to_thread.run_sync(
                                lease.__exit__,
                                type(failure) if failure is not None else None,
                                failure,
                                failure.__traceback__ if failure is not None else None,
                                limiter=anyio.CapacityLimiter(1),
                            )
                            if suppressed:
                                failure = None
                        except BaseException as exc:
                            failure = exc

        async with anyio.create_task_group() as group:
            group.start_soon(transfer)
        if failure is not None:
            raise failure
