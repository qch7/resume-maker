"""模板映射的本机结构检查和确定性修补，不调用模型"""

from resume_maker.core.errors import Problem
from resume_maker.integrations.word.templates.fill import fill_template
from resume_maker.integrations.word.templates.mapping import IMAGE_TAGS, image_container
from resume_maker.integrations.word.templates.values import missing_targets

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
