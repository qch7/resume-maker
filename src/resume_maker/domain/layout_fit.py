"""按阅读影响递增生成有限候选，是否达标始终由实际分页判断"""

from copy import deepcopy

from resume_maker.domain.page_layout import LAYOUT_KEY

FIT_TIMEOUT_SECONDS = 210
MAX_FIT_ATTEMPTS = 12


def saved_options(document):
    """保留原始选项及扩展字段，避免自动排版重置逐项样式"""
    return deepcopy(document.get("extensions", {}).get(LAYOUT_KEY, {}).get("options", {}))


def with_fit_options(document, options):
    """只替换本轮候选的排版选项，原始资料及其他扩展继续保留"""
    result = deepcopy(document)
    extensions = result.setdefault("extensions", {})
    display = extensions.get(LAYOUT_KEY, {}).get("display", {})
    extensions[LAYOUT_KEY] = {
        **extensions.get(LAYOUT_KEY, {}),
        "display": {**display, "hidden": True} if isinstance(display, dict) else {"hidden": True},
        "options": deepcopy(options),
    }
    return result


def fit_candidates(options, *, compact_honors=False):
    """先收紧空白、尝试合并荣誉，再逐步缩字，荣誉候选最多增加一轮"""
    yield deepcopy(options)
    compact_honors = compact_honors and not options.get("honors_inline")
    limit = MAX_FIT_ATTEMPTS + int(compact_honors)
    previous = options.get("auto_fit") or {}
    spacing = previous.get("spacing_factor", 1)
    delta = previous.get("font_delta", 0)
    count = 1
    for factor in (0.5, 0):
        if factor >= spacing:
            continue
        yield {**deepcopy(options), "auto_fit": {"spacing_factor": factor, "font_delta": delta}}
        count += 1
    if compact_honors:
        options = {**options, "honors_inline": True}
        yield {**deepcopy(options), "auto_fit": {"spacing_factor": 0, "font_delta": delta}}
        count += 1
    for increase in (0.5, 1, 1.5, 2, 3, 6, 12, 24, 63):
        if delta >= 63 or count >= limit:
            break
        reduced = min(63, delta + increase)
        yield {**deepcopy(options), "auto_fit": {"spacing_factor": 0, "font_delta": reduced}}
        count += 1
        if reduced == 63:
            break
