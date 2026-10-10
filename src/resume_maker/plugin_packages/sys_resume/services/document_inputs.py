"""在一个事务内固定文档输入，再交给同一生成入口"""

from resume_maker.core.content import digest
from resume_maker.core.errors import Problem, need
from resume_maker.sdk.documents import DocumentInput
from resume_maker.sdk.records import dump, unpack


def freeze_export(catalog, directory, identifier, expected_version=None):
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
        if expected_version is not None and resume["version"] != expected_version:
            raise Problem("简历已在其他窗口修改，请核对最新方案后重新导出。", 409)
        if not resume["document"]:
            raise Problem("请先填写个人资料和栏目，再导出完整简历。")
        resume["document"] = catalog.resolve_document(resume["document"], conn)
        projects = []
        for item in resume["items"]:
            revision = catalog.revision(item["revision_id"], item["project_id"], conn)
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
            template = catalog.template(resume["template_id"], conn=conn)
            data = catalog.template_bytes(template)
            if digest(data) != template["hash"]:
                raise Problem("模板文件已在程序外变化，请重新导入。", 409)
        return DocumentInput(dump(resume), dump(projects), dump(template), data)


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
            revision = catalog.revision(item["revision_id"], item["project_id"], conn)
            content = item.get("content") or revision["content"]
            selected = item["highlight_ids"]
            valid = {point["id"] for point in content["highlights"]}
            if not set(selected) <= valid or len(selected) != len(set(selected)):
                raise Problem("预览引用了不存在或重复的亮点，请重新选择。")
            projects.append({**item, "content": content})
        template = catalog.template(template_id, conn=conn) if template_id else None
        data = None
        if template:
            data = catalog.template_bytes(template)
            if digest(data) != template["hash"]:
                raise Problem("模板文件已在程序外变化，请重新导入。", 409)
        return DocumentInput(dump({"document": document}), dump(projects), dump(template), data)
