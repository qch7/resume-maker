"""经历历史树与分支指针；在数据库事务内维护不可变版本和独立草稿。"""

import unicodedata

from resume_maker.core.errors import Problem, need
from resume_maker.infrastructure.database import Database, now, uid, unpack


class History:
    """维护命名分支，每个修订只有一个所属分支，简历继续引用修订 ID。"""

    def __init__(self, db: Database):
        """复用业务数据库，分支移动与版本、草稿写入共享事务。"""
        self.db = db

    def branches(self, project_id: str) -> list[dict]:
        """列出项目分支，主分支优先，其余按创建时间稳定排序。"""
        return self.db.all(
            "SELECT * FROM experience_branches WHERE project_id=? "
            "ORDER BY is_default DESC,created_at,id",
            (project_id,),
        )

    def for_revision(self, project_id: str, revision_id: str) -> dict:
        """定位修订所属分支，同时拒绝跨项目引用。"""
        return need(
            self.db.one(
                "SELECT b.* FROM experience_branches b "
                "JOIN revision_branches r ON r.branch_id=b.id "
                "WHERE r.revision_id=? AND b.project_id=?",
                (revision_id, project_id),
            ),
            "经历版本不属于该项目。",
        )

    def initialize(self, conn, project_id: str, revision_id: str, stamp: str) -> None:
        """为新项目的初始修订登记 main，与项目创建原子完成。"""
        branch_id = f"main:{project_id}"
        conn.execute(
            "INSERT INTO experience_branches VALUES (?,?,?, ?,1,?,?)",
            (branch_id, project_id, "main", revision_id, stamp, stamp),
        )
        conn.execute("INSERT INTO revision_branches VALUES (?,?)", (revision_id, branch_id))

    def advance(self, conn, branch: dict, revision_id: str, stamp: str) -> None:
        """移动目标分支指针，只有 main 更新旧接口兼容的项目头版本。"""
        conn.execute("INSERT INTO revision_branches VALUES (?,?)", (revision_id, branch["id"]))
        conn.execute(
            "UPDATE experience_branches SET head_revision=?,updated_at=? WHERE id=?",
            (revision_id, stamp, branch["id"]),
        )
        conn.execute(
            "UPDATE projects SET head_revision=CASE WHEN ? THEN ? ELSE head_revision END,"
            "updated_at=? WHERE id=?",
            (branch["is_default"], revision_id, stamp, branch["project_id"]),
        )

    def create(self, project_id: str, revision_id: str, name: str, include_drafts: bool) -> dict:
        """从任意保存版本创建分支起点，可复制草稿但不会把草稿隐式发布。"""
        name = unicodedata.normalize("NFC", name.strip())
        if not name or len(name) > 80 or any(unicodedata.category(c).startswith("C") for c in name):
            raise Problem("分支名称须为 1 至 80 个可见字符。")
        branch_id, new_id, stamp = uid(), uid(), now()
        with self.db.transaction() as conn:
            source = need(
                unpack(
                    conn.execute(
                        "SELECT * FROM revisions WHERE id=? AND project_id=?",
                        (revision_id, project_id),
                    ).fetchone()
                ),
                "经历版本不属于该项目。",
            )
            if conn.execute(
                "SELECT 1 FROM experience_branches WHERE project_id=? AND name=?",
                (project_id, name),
            ).fetchone():
                raise Problem("该项目已存在同名分支，请换一个名称。", 409)
            number = conn.execute(
                "SELECT MAX(number)+1 FROM revisions WHERE project_id=?", (project_id,)
            ).fetchone()[0]
            # 起点也是一个独立修订，使同源分支从创建时就拥有各自的草稿空间。
            conn.execute(
                "INSERT INTO revisions SELECT ?,project_id,id,snapshot_id,?,content_json,"
                "'branch',?,? FROM revisions WHERE id=?",
                (new_id, number, f"创建分支 {name} · 基于 r{source['number']}", stamp, revision_id),
            )
            conn.execute(
                "INSERT INTO experience_branches VALUES (?,?,?,?,0,?,?)",
                (branch_id, project_id, name, new_id, stamp, stamp),
            )
            conn.execute("INSERT INTO revision_branches VALUES (?,?)", (new_id, branch_id))
            if include_drafts:
                conn.execute(
                    "INSERT INTO drafts SELECT project_id,?,field,value_json,version,origin,? "
                    "FROM drafts WHERE project_id=? AND base_revision=?",
                    (new_id, stamp, project_id, revision_id),
                )
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        return need(self.db.one("SELECT * FROM experience_branches WHERE id=?", (branch_id,)))
