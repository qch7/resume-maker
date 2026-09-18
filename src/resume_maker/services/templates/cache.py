"""复用同模板同资料结构的成功建议；命中后仍校验当前资料覆盖"""

import json
from pathlib import Path

from resume_maker.domain.templates import TemplatePlan
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.pdf.geometry import SOURCE, recovered_pdf
from resume_maker.services.templates.analysis import INSTRUCTIONS, analysis_context, assess_plan


def cache_path(directory, package, document, projects, settings) -> Path:
    """按模板、字段需求、映射契约和 AI 配置生成键；切换模型后重新识别"""
    context = analysis_context(package, document, projects)
    context.pop("template")
    context.pop("layout")
    identity = {
        "contract": (
            12
            if package.parts["word/document.xml"].get(SOURCE) == "image-v1"
            else 11
            if recovered_pdf(package.parts["word/document.xml"])
            else 10
        ),
        "provider": {
            "executable": settings.executable,
            "profile": settings.profile,
            "model": settings.model,
            "reasoning_effort": settings.reasoning_effort,
        },
        "skill": INSTRUCTIONS,
        "schema": TemplatePlan.model_json_schema(),
        "requirements": context,
        "parts": {name: digest(data) for name, data in package.files.items()},
    }
    key = digest(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode())
    return directory / "template-cache" / f"{key}.json"


def cached_plan(path, package, document, projects):
    """只接受当前仍完整有效的缓存；损坏、失效或无缓存时走正常分析"""
    try:
        plan = TemplatePlan.model_validate_json(path.read_text(encoding="utf-8"))
        review = assess_plan(package, plan, document, projects)
        return (plan, review) if review["ready"] else None
    except (OSError, ValueError):
        return None


def remember_plan(path, plan):
    """原子写入可重建的成功缓存；磁盘缓存不可用不影响已完成的分析结果"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(plan.model_dump_json(), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass
