"""模板加载、识别、检查、保存与导出共用的资料补位入口"""

from pydantic import ValidationError

from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.word.templates.sections import (
    defer_empty_sections,
    supplement_sections,
)
from resume_maker.integrations.word.templates.supplement import supplement_personal_fields
from resume_maker.integrations.word.templates.values import missing_targets


def complete_template(package, plan, document, projects, source=None):
    """仅扩展已确认结构的独立副本；需要落盘时将新节点与映射一并保存到任务快照"""
    # projects 是重复区的公开别名；模型也可能用它标识标题，需统一到实际栏目名称。
    if not any(section.title == "projects" for section in document.sections):
        project_title = next(
            section.title for section in document.sections if section.kind == "projects"
        )
        if any(field.target == "section-title:projects" for field in plan.fields):
            plan = plan.model_copy(deep=True)
            for field in plan.fields:
                if field.target == "section-title:projects":
                    field.target = f"section-title:{project_title}"
    if not package.review(plan)["ready"]:
        return package, plan, []
    original_package, original_plan = package, plan
    try:
        missing_targets(document, plan, projects)
    except Problem:
        # 重名栏目等语义冲突仍交给正式校验报告且不能在补位阶段猜测所属记录
        return package, plan, []
    plan, notices = defer_empty_sections(package, plan, document)
    package, plan, section_notices = supplement_sections(package, plan, document, projects)
    notices.extend(section_notices)
    package, plan, personal_notices = supplement_personal_fields(package, plan, document, projects)
    notices.extend(personal_notices)
    try:
        TemplatePlan.model_validate(plan.model_dump())
    except ValidationError:
        return original_package, original_plan, []
    if notices and source is not None:
        temporary = source.with_name("completed-template.docx")
        package.write(temporary)
        temporary.replace(source)
    return package, plan, notices
