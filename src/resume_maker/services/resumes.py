"""固定经历引用、简历资料解析和乐观锁保存"""

from resume_maker.core.errors import Problem, need
from resume_maker.domain.models import ResumeItem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.domain.templates import TEMPLATE_LIBRARY_KEY
from resume_maker.infrastructure.database import dump, now, uid, unpack


class Resumes:
    """简历插件拥有组合保存，经历服务仅提供不可变引用读取"""

    def __init__(self, experience, *, honor_resolver=None):
        """持有独立经历读取依赖和可撤销的资料来源解析器"""
        self.experience, self.db = experience, experience.db
        self.honor_resolver = honor_resolver

    def revision(self, revision_id, project_id=None):
        """核对不可变版本归属，不读取经历服务的内部状态"""
        return self.experience.revision(revision_id, project_id)

    def resolve_document(self, document, conn=None):
        """只通过已注册的来源解析器刷新内容，停用后保留确认快照"""
        if self.honor_resolver is None:
            return document
        return self.honor_resolver(self.db, document, conn)

    def template(self, template_id: str, include_trashed: bool = False) -> dict:
        """只允许引用具有完整映射的模板，失效引用由用户重新选择或识别"""
        template = need(
            self.db.one(
                "SELECT * FROM templates WHERE id=? AND json_type(mapping_json,'$.plan')='object'",
                (template_id,),
            ),
            "完整简历模板不可用，请重新选择模板或导入 Word 进行 AI 识别。",
        )
        library = self.db.setting(TEMPLATE_LIBRARY_KEY, {"items": {}})
        if not include_trashed and library["items"].get(template_id, {}).get("deleted_at"):
            raise Problem("该模板已移入回收站，请先恢复。", 409)
        return template

    def save_resume(
        self,
        name: str,
        template_id: str | None,
        items: list[ResumeItem],
        resume_id: str | None = None,
        version: int = 0,
        document: ResumeDocument | None = None,
    ) -> dict:
        """校验项目、版本和亮点归属并以乐观锁保存固定版本组合"""
        seen = set()
        for item in items:
            revision = self.revision(item.revision_id, item.project_id)
            valid = {h["id"] for h in revision["content"]["highlights"]}
            if item.project_id in seen or not set(item.highlight_ids) <= valid:
                raise Problem("组合包含重复项目或无效亮点。")
            if len(item.highlight_ids) != len(set(item.highlight_ids)):
                raise Problem("亮点不能重复。")
            seen.add(item.project_id)
        if template_id:
            self.template(template_id)
        resume_id = resume_id or uid()
        with self.db.transaction() as conn:
            # 引用校验必须和写入持有同一把锁，避免校验后项目被另一窗口删除
            for item in items:
                need(
                    conn.execute(
                        "SELECT id FROM revisions WHERE id=? AND project_id=?",
                        (item.revision_id, item.project_id),
                    ).fetchone(),
                    "简历中的项目已删除，请刷新后重新选择。",
                )
            if conn.execute(
                "SELECT 1 FROM resume_deletions WHERE resume_id=?", (resume_id,)
            ).fetchone():
                raise Problem("该简历方案已删除，请切换或新建方案。", 404)
            existing = unpack(
                conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
            )
            if version != (existing["version"] if existing else 0):
                raise Problem("简历组合已在其他窗口修改，请刷新。", 409)
            library = unpack(
                conn.execute(
                    "SELECT value_json FROM settings WHERE key=?", (TEMPLATE_LIBRARY_KEY,)
                ).fetchone()
            )
            deleted = library and library["value"]["items"].get(template_id, {}).get("deleted_at")
            if deleted:
                raise Problem("该模板已移入回收站，请先恢复模板或选择其他模板。", 409)
            if (
                template_id
                and not conn.execute(
                    "SELECT 1 FROM templates WHERE id=?", (template_id,)
                ).fetchone()
            ):
                raise Problem("该模板已永久删除，请选择其他模板。", 409)
            resolved_document = self.resolve_document(
                document.model_dump() if document is not None else None, conn
            )
            if resolved_document is not None and existing and existing["document"]:
                resolved_document["extensions"] = {
                    **existing["document"].get("extensions", {}),
                    **resolved_document.get("extensions", {}),
                }
            conn.execute(
                "INSERT OR REPLACE INTO resumes "
                "(id,name,template_id,items_json,version,created_at,updated_at,document_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    resume_id,
                    name.strip() or "我的简历",
                    template_id,
                    dump([i.model_dump() for i in items]),
                    version + 1,
                    existing["created_at"] if existing else now(),
                    now(),
                    dump(resolved_document) if resolved_document is not None else None,
                ),
            )
        return self.db.one("SELECT * FROM resumes WHERE id=?", (resume_id,))

    def delete_resume(self, resume_id: str, version: int) -> None:
        """按版本删除方案，保留项目、模板及历史导出，拒绝覆盖其他窗口的修改"""
        with self.db.transaction() as conn:
            resume = need(
                conn.execute(
                    "SELECT version FROM resumes WHERE id=? AND id NOT IN "
                    "(SELECT resume_id FROM resume_deletions)",
                    (resume_id,),
                ).fetchone(),
                "该简历方案不存在或已删除。",
            )
            if resume["version"] != version:
                raise Problem("简历组合已在其他窗口修改，请先载入服务器组合再删除。", 409)
            conn.execute("INSERT INTO resume_deletions VALUES (?,?)", (resume_id, now()))
