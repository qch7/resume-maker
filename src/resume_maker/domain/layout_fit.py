"""按阅读影响递增生成有限候选，是否达标始终由实际分页判断"""

from copy import deepcopy
from math import sqrt

from resume_maker.domain.page_layout import LAYOUT_KEY, current_layout_options

FIT_TIMEOUT_SECONDS = 210
MAX_FIT_ATTEMPTS = 12


def saved_options(document):
    """保留原始选项及扩展字段，避免自动排版重置逐项样式"""
    return current_layout_options(
        deepcopy(document.get("extensions", {}).get(LAYOUT_KEY, {}).get("options", {}))
    )


def with_fit_options(document, options):
    """只替换本轮候选的排版选项，原始资料及其他扩展继续保留"""
    result = deepcopy(document)
    extensions = result.setdefault("extensions", {})
    display = extensions.get(LAYOUT_KEY, {}).get("display", {})
    extensions[LAYOUT_KEY] = {
        **extensions.get(LAYOUT_KEY, {}),
        "display": {**display, "hidden": True} if isinstance(display, dict) else {"hidden": True},
        "options": current_layout_options(deepcopy(options)),
    }
    return result


def layout_cost(options):
    """优先保留较大字号，再比较分页约束及间距，评价只用于已实测候选"""
    value = options.get("auto_fit") or {}
    return (
        1 - value.get("font_scale", 1),
        bool(value.get("relax_pagination")),
        1 - value.get("spacing_factor", 1),
    )


def fit_candidates(options):
    """通过 send 接收实测页数，先收空白，再回流及比例缩字，末轮保留六磅下限"""
    options = current_layout_options(options)
    target = options.get("target_pages", 1)
    value = deepcopy(options.get("auto_fit") or {})
    pages = yield deepcopy(options)
    count = 1
    if pages is not None and pages <= target:
        return
    for factor in (0.5, 0):
        if factor >= value.get("spacing_factor", 1):
            continue
        value["spacing_factor"] = factor
        pages = yield {**deepcopy(options), "auto_fit": deepcopy(value)}
        count += 1
        if pages is not None and pages <= target:
            return
    if not value.get("relax_pagination"):
        value["relax_pagination"] = True
        pages = yield {**deepcopy(options), "auto_fit": deepcopy(value)}
        count += 1
        if pages is not None and pages <= target:
            return
    scale = value.get("font_scale", 1)
    observed = {scale: pages or target + 1}
    while count < MAX_FIT_ATTEMPTS and scale > 0:
        good = [size for size, result in observed.items() if result <= target]
        if good:
            lower = max(good)
            upper = min((size for size in observed if size > lower), default=lower)
            if upper - lower < 0.01:
                return
            next_scale = round((lower + upper) / 2, 4)
        elif count == MAX_FIT_ATTEMPTS - 1 or scale < 0.01:
            next_scale = 0
        else:
            ratio = sqrt(target / max(target + 1, pages or target + 1))
            next_scale = round(scale * min(0.9, ratio * 0.98), 4)
        if next_scale in observed:
            return
        scale = next_scale
        value["font_scale"] = scale
        pages = yield {**deepcopy(options), "auto_fit": deepcopy(value)}
        count += 1
        observed[scale] = pages or target + 1
