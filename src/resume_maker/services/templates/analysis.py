"""对模板建议自动校验和有界修正，保留最佳结果供人工核对"""

from importlib.resources import files

from resume_maker.core.errors import Problem
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.database import dump
from resume_maker.integrations.providers.base import Cancelled, StructuredOutputError
from resume_maker.integrations.word.image.header import private_image_text
from resume_maker.integrations.word.pdf.geometry import SOURCE
from resume_maker.integrations.word.templates.completion import complete_template
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.integrations.word.templates.images import image_sheets, mosaic_sources
from resume_maker.integrations.word.templates.mapping import IMAGE_TAGS, image_container
from resume_maker.integrations.word.templates.values import (
    missing_targets,
    personal_values,
    required_entry_fields,
    section_records,
)
from resume_maker.integrations.word.templates.visuals import layout_context, source_pages
from resume_maker.services.templates.schema import plan_schema

SKILL_PATH = files("resume_maker").joinpath("skills/resume-template-mapping/SKILL.md")
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


def visual_evidence(provider, package, source, workspace, flag):
    """隐私出口提供马赛克图片，原始像素和整页图留在本机"""
    document = private_image_text(package)
    if document is not None:
        provider.register_ocr(document)
    if provider.supports_mosaic_images:
        images, shown, notices = mosaic_sources(package)
        notice = "模板内嵌图片经本机马赛克处理后识别，整页原图未发送；模糊用途请人工核对。"
        return images, shown, {"available": False, "reason": notice}, [notice, *notices]
    if not provider.supports_images:
        notice = "隐私保护未发送模板图片；映射基于文字和布局结构，照片位置请人工核对。"
        return [], {}, {"available": False, "reason": notice}, [notice]
    sheets, shown = image_sheets(package, workspace)
    pages, visual, notices = source_pages(source, workspace, flag)
    return [*pages, *sheets], shown, visual, notices


def check_trial(source, plan, review, document, projects):
    """识别通过后先实际生成试填副本，提前发现栏目容器和排序约束"""
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
    """只补齐确定的空值标签并去重，绝不把未知正文或照片自动当作固定内容"""
    plan = plan.model_copy(deep=True)
    for key in ("keep", "remove", "photos"):
        setattr(plan, key, list(dict.fromkeys(getattr(plan, key))))
    removal_roots = {}
    for identifier in plan.remove:
        try:
            node = package.node(identifier)
            removal_roots[identifier] = image_container(node) if node.tag in IMAGE_TAGS else node
        except Problem:
            continue
    # 删除父段落已涵盖其图片和子段落，可移除这些冗余删除项
    roots, seen, removals = set(removal_roots.values()), set(), []
    for identifier in plan.remove:
        root = removal_roots.get(identifier)
        if root is not None:
            if root in seen or any(parent in roots for parent in root.iterancestors()):
                continue
            seen.add(root)
        removals.append(identifier)
    plan.remove = removals
    # 删除完整父块也会删除其固定装饰，keep 不能让子图片成为一枚无资料的孤立图标
    # 动态 fields 和 photos 的冲突继续由 review 检查
    deleted = package.descendants(list(removal_roots.values()))
    plan.keep = [identifier for identifier in plan.keep if identifier not in deleted]
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
    """同时核验结构和当前资料覆盖以免试填阶段才暴露漏填字段"""
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
    """以列定义和部件分组压缩清单，完整保留精确文字、同级及祖先约束"""
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
    """提供模板原文、栏目和所需字段名，用户当前填写的个人资料值不发送给模型"""
    requirements = {}
    for section in document.sections:
        records = section_records(document, section.title, projects)
        requirements["projects" if section.kind == "projects" else section.title] = (
            required_entry_fields(records, project=section.kind == "projects")
        )
    context = {
        "sections": [
            {"id": s.id, "title": s.title, "kind": s.kind, "parent_id": s.parent_id}
            for s in document.sections
        ],
        # 某些上游不执行 API 的结构化输出参数，正文也携带同一领域模型的字段契约
        "output_schema": TemplatePlan.model_json_schema(),
        "completion_policy": {
            "missing_personal_text": "omit_binding",
            "missing_entry_fields": "omit_binding",
            "missing_section": "omit_repeat",
            "explanation": (
                "仅识别模板现有内容；缺少字段和普通栏目（含子栏目）由程序复制样式后补齐。"
                "不要为满足 required 字段占用页首或栏目间的空白。"
                "项目已有完整样本时，缺少的角色、技术栈、描述和亮点也由程序补齐。"
            ),
        },
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
    if package.parts["word/document.xml"].get(SOURCE) == "image-v1":
        context["image_layout_constraints"] = (
            "这是保留位置证据的图片恢复模板。姓名、联系方式、顶部学历/工作摘要共用的页首"
            "表格属于个人资料区，不将其中某一个摘要单元格设为教育或工作经历的重复区。"
            "顶部摘要可完整映射到个人自定义字段（当前无值时自动隐藏）；完整栏目请选独立"
            "经历样本或补充位置。真正含有栏目标题的侧栏表格保留分栏结构。"
            "照片与小图标按已提供的图片节点区分，图标保持固定，头像单独映射。"
        )
    return context


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
    """最多分析三轮，把具体校验反馈交回 AI，失败或退步时保留已有最佳建议"""
    source = workspace / "original.docx"
    if initial is not None and not feedback:
        package, initial, notices = complete_template(
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
    images, shown, visual, visual_notices = visual_evidence(
        provider, package, source, workspace, flag
    )
    evidence_source = source.read_bytes()
    context["visible_images"] = shown
    context["source_pages"] = visual
    context["image_instructions"] = (
        "附件为带节点编号的马赛克图片拼图，整页原图未发送。"
        "结合图片中仍可见的轮廓、布局和节点信息判断照片或装饰用途；"
        "不要推测身份、恢复被遮盖细节，无法区分时写入 warnings 并保留待确认。"
        if provider.supports_mosaic_images
        else "附件先为 source_pages 指定的源模板整页图，再为标注节点的图片拼图。"
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
    format_issues = []
    usage_by_thread = {}

    def receive(kind, data):
        """捕获本次模板会话用于增量修正并转发公开进度，不借用其他任务会话"""
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
            # 补充结构后重新发送对应快照的清单和图片并新建识别会话
            context.update(analysis_context(package, document, projects))
            images, shown, visual, visual_notices = visual_evidence(
                provider, package, source, workspace, flag
            )
            context.update(source_pages=visual, visible_images=shown)
            evidence_source = source.read_bytes()
            thread_id = None
        stage = (
            "正在识别资料和栏目"
            if candidate is None and not format_issues
            else "正在自动补全和修正"
        )
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
            request["validation"]["issues"] = validation.get("issues", [])
            issue_nodes = {
                node for issue in validation.get("issues", []) for node in issue["nodes"]
            }
            request["validation"]["node_context"] = compact_inventory(
                {"nodes": [row for row in package.inventory()["nodes"] if row["id"] in issue_nodes]}
            )
            request["validation"]["unresolved"] = compact_inventory(
                {"nodes": validation["unresolved"]}
            )
            request["repair_instructions"] = (
                "保留正确映射，逐项修复校验问题、未识别原文和缺少的资料位置，返回完整方案。"
            )
        if feedback:
            request["user_feedback"] = feedback
        if format_issues:
            request["format_validation"] = format_issues
            request["repair_instructions"] = (
                "上次输出没有通过结构化校验。请按字段路径修正类型或候选值，"
                "节点必须来自相应类别的真实清单；照片须使用 image 节点，不能用容器编号。"
                "不要更改正确内容，返回符合 schema 的完整 JSON。"
            )
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
            attempts += 1
            result = provider.run_structured(
                result_model=plan_schema(package, document),
                workspace=workspace,
                prompt=prompt,
                thread_id=thread_id,
                settings=settings,
                cancelled=flag,
                emit=receive,
                images=[] if resuming else images,
            )
            format_issues, last_error = [], None
            if flag.is_set():
                raise Cancelled("模板分析已取消。")
            emit(
                "activity",
                {"type": "validation", "text": f"第 {attempt} 轮识别已返回，正在检查覆盖与边界"},
            )
            last_raw = TemplatePlan.model_validate(result.model_dump())
            updated = complete_labels(package, last_raw)
            package, updated, notices = complete_template(
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
        except StructuredOutputError as exc:
            if flag.is_set():
                raise Cancelled("模板分析已取消。") from exc
            format_issues, last_error = exc.issues, str(exc)
            emit(
                "activity",
                {"type": "validation", "text": "输出格式未通过校验，已反馈具体字段路径。"},
            )
            if attempt == 3:
                if best is None:
                    raise
                break
        except Exception as exc:
            if best is None:
                raise
            last_error = str(exc)
            break
    if flag.is_set():
        raise Cancelled("模板分析已取消。")
    # 最佳方案和源快照必须一起恢复，失败轮次新增的节点不能污染此前仍可核对的方案
    if best_source is not None and source.read_bytes() != best_source:
        temporary = source.with_name("best-source.docx")
        temporary.write_bytes(best_source)
        temporary.replace(source)
    best_review["notices"].extend(visual_notices)
    return best, best_review, attempts, last_error
