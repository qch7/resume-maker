"""只通过公开 Context 读写当前实例的笔记"""

from resume_maker.sdk.context import Context


def activate(context: Context) -> None:
    """注册笔记操作和查询，持久资料在停用后保留"""
    data = context.data
    running = [False]

    def start() -> None:
        """所有能力就绪后接受请求"""
        running[0] = True

    def stop() -> None:
        """停止处理当前实例的新请求"""
        running[0] = False

    def read(_payload: None) -> str:
        """读取当前实例已保存的笔记"""
        if not running[0]:
            raise RuntimeError("笔记实例未启动")
        return data.get("note").value or ""

    def save(payload: str) -> str:
        """按当前资料版本保存，冲突不覆盖已有笔记"""
        return data.set("note", payload, data.get("note").version).value

    def summary(_connection, state: dict) -> None:
        """通过贡献添加独立实例摘要，不读取宿主私有实现"""
        state.setdefault("plugin_notes", {})[context.instance_id] = {
            "title": context.config["title"],
            "text": read(None),
        }

    context.lifecycle(start, stop)
    context.rpc("read", read)
    context.rpc("save", save)
    context.contribute("workspace.queries", "community.notes/summary", summary)
