"""自动排版只采用实际测得的页数，候选不修改草稿或正式方案"""

import time
from contextlib import ExitStack

from resume_maker.domain.extensions import display_document
from resume_maker.domain.layout_fit import (
    fit_candidates,
    layout_cost,
    saved_options,
    with_fit_options,
)
from resume_maker.sdk.documents import check_document_work, current_document_work


def fit_preview(service, frozen, *, force=False):
    """有限顺序搜索保留最少修改的达标候选，失败时保留本轮最佳实测结果"""
    original = frozen.resume["document"]
    options = saved_options(original)
    target = options.get("target_pages", 1)
    baseline = best = None
    attempts = 0
    status, message = "unfit", "已尝试六磅下限及安全回流，仍超过预算，请调整内容或模板。"
    search = fit_candidates(options)
    candidate = next(search)
    measurements = {}
    last_duration = 0
    with ExitStack() as retained:
        while candidate is not None:
            check_document_work()
            work = current_document_work()
            if (
                best is not None
                and best["measured"]["result"]["pages"] <= target
                and work is not None
                and work.deadline - time.monotonic() < max(2, last_duration * 2 + 1)
            ):
                break
            pending = ExitStack()
            retained.callback(pending.close)
            document = display_document(
                original if attempts == 0 else with_fit_options(original, candidate)
            )
            started = time.monotonic()
            measured = pending.enter_context(service.measure(frozen, document, force, measurements))
            if not measured.get("duplicate"):
                last_duration = max(last_duration, time.monotonic() - started)
            current = {"measured": measured, "options": candidate, "scope": pending}
            attempts += 1
            if baseline is None:
                baseline = best = current
            pages, error = measured["result"]["pages"], measured["result"]["render_error"]
            if type(pages) is not int or pages < 1 or error:
                prior = best["measured"]["result"]
                if (
                    type(prior["pages"]) is int
                    and 0 < prior["pages"] <= target
                    and not prior["render_error"]
                ):
                    break
                status = "unavailable"
                message = error or "无法取得实际页数，已保留原排版。"
                best = baseline
                break
            best_pages = best["measured"]["result"]["pages"]
            better = (
                best_pages > target or layout_cost(candidate) < layout_cost(best["options"])
                if pages <= target
                else best_pages > target and pages < best_pages
            )
            if better and not measured.get("duplicate"):
                if best is not baseline:
                    best["scope"].close()
                best = current
            elif current is not baseline:
                pending.close()
            try:
                candidate = search.send(pages)
            except StopIteration:
                candidate = None
        check_document_work()
        preview = service.publish(frozen, best["measured"])
        if status != "unavailable" and preview["pages"] <= target:
            status = "unchanged" if best is baseline else "fit"
            message = "当前排版已在预算内。" if best is baseline else "已按实际分页调整到预算内。"
        return {
            "status": status,
            "options": best["options"],
            "pages": preview["pages"],
            "attempts": attempts,
            "preview": preview,
            "message": message,
        }
