"""只向任务进度发布固定阶段、真实工具计数，不发布参数或模型正文"""


class SourceProgress:
    """在受信任源码通道完成读取后汇总当前任务的实际进展"""

    def __init__(self, emit):
        """仅在本轮内保存已读文件身份，不向前端传递文件路径"""
        self.emit, self.calls, self.files = emit, 0, set()

    def read(self, name, arguments):
        """成功调用源码工具后更新计数，分段重复读取同一文件只计一次"""
        self.calls += 1
        if name == "read_source":
            self.files.add((arguments["source"], arguments["path"]))
        self.emit(
            "activity",
            {
                "type": "source_progress",
                "text": f"已读取 {len(self.files)} 个源码文件，完成 {self.calls} 次源码工具调用",
                "files_read": len(self.files),
                "tool_calls": self.calls,
            },
        )
