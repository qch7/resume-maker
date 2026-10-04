"""固定经历引用、简历资料解析和乐观锁保存"""

from resume_maker.core.errors import Problem, need
from resume_maker.domain.models import ResumeItem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.sdk.observation import internal
from resume_maker.sdk.records import dump, now, uid, unpack


class Resumes:
    """简历插件拥有组合保存，经历服务仅提供不可变引用读取"""

    def __init__(self, experience, *, storage, sources=None, assets=None):
        """持有独立经历读取依赖和可撤销的资料来源解析器"""
        self.experience, self.db = experience, storage
        self.sources = sources
        self.assets = assets

    @internal
    def workspace_state(self, conn):
        """在调用方快照内返回本模块拥有的工作台资料"""
        result = {
            "resumes": [
                unpack(row)
                for row in conn.execute(
                    "SELECT * FROM resumes WHERE id NOT IN "
                    "(SELECT resume_id FROM resume_deletions) ORDER BY updated_at DESC"
                )
            ],
        }
        for resume in result["resumes"]:
            resume["document"] = self.resolve_document(resume["document"], conn)
        return result

    def template_bytes(self, template, directory):
        """通过统一资源读取模板原件，独立调用兼容旧文件布局"""
        if self.assets:
            return self.assets.read_file(f"templates/{template['id']}", "template.docx")
        return (directory / "templates" / template["id"] / "template.docx").read_bytes()

    def freeze_export(self, directory, identifier):
        """在同一快照固定成品所需的简历、修订和模板输入"""
        from resume_maker.services.document_inputs import freeze_export

        return freeze_export(self, directory, identifier)

    def freeze_preview(self, directory, template_id, document, items):
        """在同一快照固定工作副本和可选模板输入"""
        from resume_maker.services.document_inputs import freeze_preview

        return freeze_preview(self, directory, template_id, document, items)

    def revision(self, revision_id, project_id=None, conn=None):
        """核对不可变版本归属，不读取经历服务的内部状态"""
        return self.experience.revision(revision_id, project_id, conn)

    def resolve_document(self, document, conn=None):
        """只通过已注册的来源解析器刷新内容，停用后保留确认快照"""
        if self.sources is None:
            return document
        return self.sources.resolve(document, conn)

    def source_catalog(self):
        """列出当前可选择的资料提供方"""
        return self.sources.describe() if self.sources else []

    def source_items(self, provider, cursor=None, query="", limit=50):
        """从明确选择的来源读取有界资料页"""
        if self.sources is None:
            raise Problem("资料来源未启用。", 409)
        return self.sources.browse(provider, cursor, query, limit)

    def preserve_sources(self, conn=None):
        """来源停用或删除前保存最新确认内容，更新版本以保护已有草稿"""
        if conn is None:
            with self.db.transaction() as connection:
                return self.preserve_sources(connection)
        rows = conn.execute("SELECT id,document_json FROM resumes WHERE document_json IS NOT NULL")
        for row in rows.fetchall():
            resume = unpack(row)
            updated = self.resolve_document(resume["document"], conn)
            if updated != resume["document"]:
                ResumeDocument.model_validate(updated)
                conn.execute(
                    "UPDATE resumes SET document_json=?,version=version+1,updated_at=? WHERE id=?",
                    (dump(updated), now(), resume["id"]),
                )

    def template(self, template_id: str, include_trashed: bool = False, conn=None) -> dict:
        """读取模板所有者发布的稳定引用，停用插件仍保留资料和引用校验"""
        template = need(
            self.db.reference("template", template_id, conn),
            "完整简历模板不可用，请重新选择模板或导入 Word 进行 AI 识别。",
        )
        if not isinstance(template.get("mapping", {}).get("plan"), dict):
            raise Problem("完整简历模板不可用，请重新选择模板或导入 Word 进行 AI 识别。", 409)
        if template.pop("_deleted_at", None) and not include_trashed:
            raise Problem("该模板已移入回收站，请先恢复。", 409)
        return template

    def template_usage(self, conn, identifier):
        """在模板维护事务内返回全部保存方案引用，包含历史成品所在方案"""
        return [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM resumes WHERE template_id=? ORDER BY created_at",
                (identifier,),
            )
        ]

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
                self.experience.revision(item.revision_id, item.project_id, conn)
            if conn.execute(
                "SELECT 1 FROM resume_deletions WHERE resume_id=?", (resume_id,)
            ).fetchone():
                raise Problem("该简历方案已删除，请切换或新建方案。", 404)
            existing = unpack(
                conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
            )
            if version != (existing["version"] if existing else 0):
                raise Problem("简历组合已在其他窗口修改，请刷新。", 409)
            if template_id:
                self.template(template_id, conn=conn)
            resolved_document = self.resolve_document(
                document.model_dump() if document is not None else None, conn
            )
            if resolved_document is not None and existing and existing["document"]:
                resolved_document["extensions"] = {
                    **existing["document"].get("extensions", {}),
                    **resolved_document.get("extensions", {}),
                }
            if resolved_document is not None:
                ResumeDocument.model_validate(resolved_document)
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
