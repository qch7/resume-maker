"""模板加载、识别、检查、保存与导出共用的资料补位入口"""

from pydantic import ValidationError

from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.word.templates.sections import supplement_sections
from resume_maker.integrations.word.templates.supplement import supplement_personal_fields
from resume_maker.integrations.word.templates.values import missing_targets


def complete_template(package, plan, document, projects, source=None):
    """仅扩展已确认结构的独立副本；需要落盘时将新节点与映射一并保存到任务快照"""
    if not package.review(plan)["ready"]:
        return package, plan, []
    original_package, original_plan = package, plan
    try:
        missing_targets(document, plan, projects)
    except Problem:
        # 重名栏目等语义冲突仍交给正式校验报告且不能在补位阶段猜测所属记录
        return package, plan, []
    package, plan, notices = supplement_sections(package, plan, document, projects)
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
