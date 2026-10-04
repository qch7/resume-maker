"""在一个事务内固定文档输入，再交给同一生成入口"""

from resume_maker.core.errors import Problem, need
from resume_maker.domain.templates import TEMPLATE_LIBRARY_KEY, TemplatePlan
from resume_maker.infrastructure.database import dump, unpack
from resume_maker.integrations.sources import digest
from resume_maker.sdk.documents import DocumentInput


def freeze_export(catalog, directory, identifier):
    """固定简历版本、来源内容、映射和原件，写锁只覆盖短暂的本地读取"""
    with catalog.db.transaction() as conn:
        resume = need(
            unpack(
                conn.execute(
                    "SELECT * FROM resumes WHERE id=? AND id NOT IN "
                    "(SELECT resume_id FROM resume_deletions)",
                    (identifier,),
                ).fetchone()
            ),
            "该简历方案不存在或已删除。",
        )
        if not resume["document"]:
            raise Problem("请先填写个人资料和栏目，再导出完整简历。")
        resume["document"] = catalog.resolve_document(resume["document"], conn)
        projects = []
        for item in resume["items"]:
            revision = need(
                unpack(
                    conn.execute(
                        "SELECT * FROM revisions WHERE id=? AND project_id=?",
                        (item["revision_id"], item["project_id"]),
                    ).fetchone()
                ),
                "简历引用的经历版本已不可用。",
            )
            projects.append(
                {
                    **item,
                    "revision_number": revision["number"],
                    "snapshot_id": revision["snapshot_id"],
                    "content": revision["content"],
                }
            )
        template, data = None, None
        if resume["template_id"]:
            template = need(
                unpack(
                    conn.execute(
                        "SELECT * FROM templates WHERE id=? "
                        "AND json_type(mapping_json,'$.plan')='object'",
                        (resume["template_id"],),
                    ).fetchone()
                ),
                "完整简历模板不可用，请重新选择模板或导入 Word 进行 AI 识别。",
            )
            library = unpack(
                conn.execute(
                    "SELECT value_json FROM settings WHERE key=?", (TEMPLATE_LIBRARY_KEY,)
                ).fetchone()
            )
            if library and library["value"].get("items", {}).get(template["id"], {}).get(
                "deleted_at"
            ):
                raise Problem("该模板已移入回收站，请先恢复。", 409)
            data = (directory / "templates" / template["id"] / "template.docx").read_bytes()
            if digest(data) != template["hash"]:
                raise Problem("模板文件已在程序外变化，请重新导入。", 409)
        return DocumentInput(dump(resume), dump(projects), dump(template), data)


def generate_docx(
    output, document, projects, *, engine, template_data=None, plan=None, template_engine=None
):
    """正式导出、预览和模板试填共享输入副本及引擎调用规则"""
    if template_data is None:
        engine(output, document, projects)
        return
    if template_engine is None:
        raise Problem("此文档需要的模板引擎未启用。", 409)
    source = output.parent / "input-template.docx"
    source.write_bytes(template_data)
    template_engine(source, output, TemplatePlan.model_validate(plan), document, projects)


def freeze_preview(catalog, directory, template_id, document, items):
    """预览也在同一读取事务固定来源、经历和模板，工作副本作为显式输入保留"""
    if document is None:
        raise Problem("请先填写个人资料和栏目。")
    if len({item["project_id"] for item in items}) != len(items):
        raise Problem("项目引用不能重复。")
    with catalog.db.transaction() as conn:
        document = catalog.resolve_document(document, conn)
        projects = []
        for item in items:
            revision = need(
                unpack(
                    conn.execute(
                        "SELECT * FROM revisions WHERE id=? AND project_id=?",
                        (item["revision_id"], item["project_id"]),
                    ).fetchone()
                ),
                "经历版本不属于该项目。",
            )
            content = item.get("content") or revision["content"]
            selected = item["highlight_ids"]
            valid = {point["id"] for point in content["highlights"]}
            if not set(selected) <= valid or len(selected) != len(set(selected)):
                raise Problem("预览引用了不存在或重复的亮点，请重新选择。")
            projects.append({**item, "content": content})
        template = catalog.template(template_id) if template_id else None
        data = None
        if template:
            data = (directory / "templates" / template_id / "template.docx").read_bytes()
            if digest(data) != template["hash"]:
                raise Problem("模板文件已在程序外变化，请重新导入。", 409)
        return DocumentInput(dump({"document": document}), dump(projects), dump(template), data)
