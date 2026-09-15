"""对模板建议自动校验和有界修正，保留最佳结果供人工核对。"""

from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.database import dump
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.integrations.word.template_fill import (
    fill_template,
    missing_targets,
    personal_values,
    section_records,
)
from resume_maker.integrations.word.template_images import image_sheets
from resume_maker.integrations.word.template_supplement import supplement_personal_fields
from resume_maker.integrations.word.template_visuals import layout_context, source_pages

SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/resume-template-mapping/SKILL.md"
INSTRUCTIONS = SKILL_PATH.read_text(encoding="utf-8")

FIXED_LABELS = {
    "姓名",
    "性别",
    "年龄",
    "电话",
    "联系电话",
    "手机",
    "邮箱",
    "电子邮箱",
    "求职意向",
    "所在城市",
    "个人主页",
    "项目名称",
    "项目时间",
    "项目描述",
    "项目介绍",
    "项目职责",
    "项目背景",
    "项目成果",
    "项目亮点",
    "担任角色",
    "技术栈",
    "教育背景",
    "毕业院校",
    "学校",
    "专业",
    "学历",
    "学位",
    "时间",
}


def check_trial(source, plan, review, document, projects):
    """识别通过后先实际生成试填副本，提前发现栏目容器与排序约束。"""
    if review["ready"]:
        output = source.parent / "layout-check.docx"
        try:
            notices = fill_template(source, output, plan, document.model_dump(), projects)
            review["notices"] = list(dict.fromkeys([*review.get("notices", []), *notices]))
        except Problem as exc:
            review["errors"].append(str(exc))
            review["ready"] = False
        finally:
            output.unlink(missing_ok=True)
    return review


def complete_labels(package, plan):
    """只补齐确定的空值标签并去重，绝不把未知正文或照片自动当作固定内容。"""
    plan = plan.model_copy(deep=True)
    for key in ("keep", "remove", "photos"):
        setattr(plan, key, list(dict.fromkeys(getattr(plan, key))))
    claimed = {field.node for field in plan.fields}
    claimed.update(field.node for region in plan.repeats for field in region.fields)
    for identifier in plan.remove:
        try:
            claimed |= package.descendants([package.node(identifier)])
        except Problem:
            continue
    for row in package.inventory()["nodes"]:
        if (
            row["kind"] == "p"
            and row["id"] not in claimed
            and row["text"].strip().rstrip(":：").strip() in FIXED_LABELS
            and row["id"] not in plan.keep
        ):
            plan.keep.append(row["id"])
    return plan


def assess_plan(package, plan, document, projects):
    """同时核验结构与当前资料覆盖，避免试填阶段才暴露漏填字段。"""
    review = package.review(plan)
    try:
        missing = missing_targets(document, plan, projects)
    except Problem as exc:
        missing = [str(exc)]
    review["missing"] = missing
    review["notices"] = []
    review["ready"] = review["ready"] and not missing
    return review


def compact_inventory(inventory):
    """以列定义和部件分组压缩清单，完整保留精确文字、同级及祖先约束。"""
    parts = {}
    for node in inventory["nodes"]:
        parts.setdefault(node["part"], []).append(
            [
                node["id"],
                node["kind"],
                node["parent"],
                node["ancestors"],
                node["text"] if node["kind"] in {"p", "image"} else "",
                node["can_insert"],
            ]
        )
    return {"columns": ["id", "kind", "parent", "ancestors", "text", "can_insert"], "parts": parts}


def analysis_context(package, document, projects):
    """提供模板原文、栏目和所需字段名，用户当前填写的个人资料值不发送给模型。"""
    requirements = {}
    for section in document.sections:
        records = section_records(document, section.title, projects)
        allowed = (
            ("title", "period", "role", "stack", "description", "highlights")
            if section.kind == "projects"
            else ("title", "subtitle", "period", "details", "custom_fields")
        )
        requirements["projects" if section.kind == "projects" else section.title] = [
            field for field in allowed if any(record.get(field) for record in records)
        ]
    return {
        "sections": [{"title": s.title, "kind": s.kind} for s in document.sections],
        "custom_labels": [field.label for field in document.personal.custom_fields],
        "required_personal_fields": [
            target
            for target, value in personal_values(document).items()
            if target.startswith("personal.") and value and target != "personal.custom_fields"
        ],
        "required_entry_fields": requirements,
        "template": compact_inventory(package.inventory()),
        "layout": layout_context(package),
    }


def analyze_plan(
    package,
    provider,
    workspace,
    document,
    projects,
    settings,
    flag,
    emit,
    initial=None,
    feedback="",
):
    """最多分析三轮，把具体校验反馈交回 AI；失败或退步时保留已有最佳建议。"""
    source = workspace / "original.docx"
    if initial is not None and not feedback:
        package, initial, notices = supplement_personal_fields(
            package, complete_labels(package, initial), document, projects, source
        )
        if notices:
            for text in notices:
                emit("activity", {"type": "repair", "text": text})
            review = check_trial(
                source,
                initial,
                assess_plan(package, initial, document, projects),
                document,
                projects,
            )
            review["notices"].extend(notices)
            if review["ready"]:
                return initial, review, 0, None
    context = analysis_context(package, document, projects)
    emit("activity", {"type": "prepare", "text": "正在准备模板清单与图片"})
    sheets, shown = image_sheets(package, workspace)
    pages, visual, visual_notices = source_pages(source, workspace, flag)
    images = [*pages, *sheets]
    evidence_source = source.read_bytes()
    context["visible_images"] = shown
    context["source_pages"] = visual
    context["image_instructions"] = (
        "附件先为 source_pages 指定的源模板整页图，再为标注节点的图片拼图。"
        "结合整页的空间关系、layout 中的显式换行和制表位及 template 中的精确原文映射；"
        "不能由字段名字、编号顺序或图片尺寸推测位置。缺少整页证据时不要声称已验证视觉布局。"
    )
    candidate = initial
    best, best_review, best_source = None, None, None
    candidate_review = None
    if candidate is not None:
        candidate = complete_labels(package, candidate)
        best, best_review = (
            candidate,
            check_trial(
                source,
                candidate,
                assess_plan(package, candidate, document, projects),
                document,
                projects,
            ),
        )
        candidate_review = best_review
        best_source = source.read_bytes()
    last_error = None
    attempts = 0
    thread_id = None
    last_raw = None
    usage_by_thread = {}

    def receive(kind, data):
        """捕获本次模板会话用于增量修正，并转发公开进度；不借用其他任务会话。"""
        nonlocal thread_id
        if kind == "thread":
            thread_id = data["id"]
        elif kind == "usage" and data.get("cumulative") and thread_id:
            previous = usage_by_thread.get(thread_id, {})
            usage_by_thread[thread_id] = data
            data = {
                key: max(0, value - previous.get(key, 0))
                for key, value in data.items()
                if key != "cumulative" and isinstance(value, int) and value >= 0
            }
        emit(kind, data)

    for attempt in range(1, 4):
        if flag.is_set():
            raise Cancelled("模板分析已取消。")
        if source.read_bytes() != evidence_source:
            # 补充结构后节点编号可能全部变化，重发对应快照的清单和图片，不能续用旧编号会话。
            context.update(analysis_context(package, document, projects))
            pages, visual, visual_notices = source_pages(source, workspace, flag)
            sheets, shown = image_sheets(package, workspace)
            images = [*pages, *sheets]
            context.update(source_pages=visual, visible_images=shown)
            evidence_source = source.read_bytes()
            thread_id = None
        stage = "正在识别资料和栏目" if candidate is None else "正在自动补全和修正"
        emit(
            "activity", {"type": "analysis", "round": attempt, "text": f"{stage} · 第 {attempt} 轮"}
        )
        resuming = bool(thread_id)
        request = {} if resuming else dict(context)
        if candidate is not None:
            if not resuming or candidate != last_raw:
                request["previous_plan"] = candidate.model_dump()
            validation = candidate_review
            request["validation"] = {
                key: validation[key] for key in ("errors", "missing", "unresolved")
            }
            request["validation"]["unresolved"] = compact_inventory(
                {"nodes": validation["unresolved"]}
            )
            request["repair_instructions"] = (
                "保留正确映射，逐项修复校验问题、未识别原文和缺少的资料位置，返回完整方案。"
            )
        if feedback:
            request["user_feedback"] = feedback
        try:
            prompt = (
                (
                    "继续使用 resume-template-mapping skill 和前文清单、图片，仅修正以下反馈。"
                    if resuming
                    else INSTRUCTIONS
                )
                + "\n"
                + dump(request)
            )
            emit(
                "metrics",
                {
                    "round": attempt,
                    "prompt_chars": len(prompt),
                    "images": 0 if resuming else len(images),
                    "resumed": resuming,
                },
            )
            result = provider.run_structured(
                result_model=TemplatePlan,
                workspace=workspace,
                prompt=prompt,
                thread_id=thread_id,
                settings=settings,
                cancelled=flag,
                emit=receive,
                images=[] if resuming else images,
            )
            attempts += 1
            if flag.is_set():
                raise Cancelled("模板分析已取消。")
            emit(
                "activity",
                {"type": "validation", "text": f"第 {attempt} 轮识别已返回，正在检查覆盖与边界"},
            )
            last_raw = TemplatePlan.model_validate(result.model_dump())
            updated = complete_labels(package, last_raw)
            package, updated, notices = supplement_personal_fields(
                package, updated, document, projects, source
            )
            for text in notices:
                emit("activity", {"type": "repair", "text": text})
            review = check_trial(
                source,
                updated,
                assess_plan(package, updated, document, projects),
                document,
                projects,
            )
            review["notices"].extend(notices)
            score = (len(review["errors"]), len(review["missing"]), len(review["unresolved"]))
            previous_score = (
                (
                    len(best_review["errors"]),
                    len(best_review["missing"]),
                    len(best_review["unresolved"]),
                )
                if best_review
                else (float("inf"), float("inf"), float("inf"))
            )
            if score <= previous_score:
                best, best_review = updated, review
                best_source = source.read_bytes()
            if review["ready"] or (candidate and updated == candidate):
                break
            candidate = updated
            candidate_review = review
        except Cancelled:
            raise
        except Exception as exc:
            if best is None:
                raise
            last_error = str(exc)
            break
    if flag.is_set():
        raise Cancelled("模板分析已取消。")
    # 最佳方案与源快照必须一起恢复，失败轮次新增的节点不能污染此前仍可核对的方案。
    if best_source is not None and source.read_bytes() != best_source:
        temporary = source.with_name("best-source.docx")
        temporary.write_bytes(best_source)
        temporary.replace(source)
    best_review["notices"].extend(visual_notices)
    return best, best_review, attempts, last_error
