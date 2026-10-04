"""模板适配器拥有的资料仓库，供模板库通过公开事务接口维护"""

from resume_maker.core.errors import need
from resume_maker.sdk.records import unpack


class TemplateRecords:
    """元信息、映射和稳定引用由模板表的同事务发布规则保持一致"""

    def list(self, conn, *, excluding=None):
        """在已有快照返回独立模板记录"""
        return [
            unpack(row)
            for row in conn.execute("SELECT * FROM templates ORDER BY created_at DESC")
            if row["id"] != excluding
        ]

    def get(self, conn, identifier):
        """核验模板仍存在后返回持久记录"""
        return need(
            unpack(conn.execute("SELECT * FROM templates WHERE id=?", (identifier,)).fetchone()),
            "该模板不存在或已永久删除。",
        )

    def rename(self, conn, identifier, name):
        """名称更新和公共引用摘要在同一事务完成"""
        self.get(conn, identifier)
        conn.execute("UPDATE templates SET name=? WHERE id=?", (name, identifier))

    def delete(self, conn, identifier):
        """资料删除和公共引用失效在同一事务完成"""
        self.get(conn, identifier)
        conn.execute("DELETE FROM templates WHERE id=?", (identifier,))
