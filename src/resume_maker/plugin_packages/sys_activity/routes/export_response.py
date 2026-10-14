"""日志导出响应在下载结束后显式释放快照游标及连接"""

import anyio
from starlette.responses import StreamingResponse


class ActivityExportResponse(StreamingResponse):
    """同步日志生成器只在后台迭代结束后关闭"""

    def __init__(self, content, **kwargs):
        """保留原始生成器，异步包装不负责关闭其内部的数据库快照"""
        self.export = content
        super().__init__(content, **kwargs)

    async def __call__(self, scope, receive, send):
        """父请求取消仍等待后台读取、快照关闭，传输异常保持原类型"""
        failure = cleanup_failure = None

        async def transfer():
            """子任务取消不抛弃正在执行的 next，完整收尾后才结束请求作用域"""
            nonlocal failure, cleanup_failure

            async def send_current(message):
                """后台读取返回后先检查取消，不能继续发送刚取出的旧批次"""
                await anyio.lowlevel.checkpoint_if_cancelled()
                await send(message)

            try:
                await super(ActivityExportResponse, self).__call__(scope, receive, send_current)
            except BaseException as exc:
                failure = exc
            finally:
                with anyio.CancelScope(shield=True):
                    try:
                        try:
                            # 关闭不争用读取线程额度，父任务重复取消也必须等到释放连接
                            await anyio.to_thread.run_sync(
                                self.export.close, limiter=anyio.CapacityLimiter(1)
                            )
                        finally:
                            await self.body_iterator.aclose()
                    except BaseException as exc:
                        cleanup_failure = exc

        async with anyio.create_task_group() as group:
            group.start_soon(transfer)
        if failure is not None:
            raise failure from cleanup_failure
        if cleanup_failure is not None:
            raise cleanup_failure
