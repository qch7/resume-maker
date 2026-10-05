"""同一读取事务聚合各模块公开的工作台查询"""


class Workspace:
    """聚合器持有查询协议，不读取业务表或其他服务内部对象"""

    def __init__(self, storage, *, readers, contributors=None):
        """读取器由组合根明确注入，扩展贡献随作用域撤销"""
        self.db, self.readers = storage, tuple(readers)
        self.contributors = contributors or (lambda: ())

    def state(self):
        """所有系统读取和扩展贡献共用一个快照，避免混用不同版本的资料"""
        with self.db.connect() as conn:
            conn.execute("BEGIN")
            state = {"honors": [], "conversations": [], "templates": [], "jobs": []}
            for reader in self.readers:
                state.update(reader(conn))
            for contribute in self.contributors():
                contribute.value(conn, state)
            return state
