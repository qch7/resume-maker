"""自动排版只采用实际测得的页数，候选不修改草稿或正式方案"""

from contextlib import ExitStack

from resume_maker.domain.extensions import display_document
from resume_maker.domain.layout_fit import fit_candidates, saved_options, with_fit_options
from resume_maker.domain.resume import ResumeDocument
from resume_maker.integrations.word.full_resume import displayed_entries
from resume_maker.integrations.word.page_layout import inline_honor
from resume_maker.sdk.documents import check_document_work


def compactable_honors(document):
    """沿用文档引擎的可见荣誉规则，只为实际能合并的多个字段或行增加候选"""
    resume = ResumeDocument.model_validate(document)
    for section in resume.sections:
        if not section.visible or any(
            parent.id == section.parent_id and not parent.visible for parent in resume.sections
        ):
            continue
        for entry in displayed_entries(section):
            if inline_honor(entry, section, True) is None:
                continue
            values = [entry.title, entry.subtitle, entry.period, entry.details]
            values.extend(field.value for field in entry.custom_fields)
            if sum(bool(value) for value in values) > 1 or any("\n" in value for value in values):
                return True
    return False


def fit_preview(service, frozen, *, force=False):
    """有限顺序搜索保留最少修改的达标候选，失败时保留本轮最佳实测结果"""
    original = frozen.resume["document"]
    options = saved_options(original)
    target = options.get("target_pages", 1)
    baseline = best = None
    attempts = 0
    status, message = "unfit", "在本轮可读范围内仍超过页数预算，请调整内容或模板。"
    with ExitStack() as retained:
        for candidate in fit_candidates(options, compact_honors=compactable_honors(original)):
            check_document_work()
            pending = ExitStack()
            retained.callback(pending.close)
            document = display_document(
                original if attempts == 0 else with_fit_options(original, candidate)
            )
            measured = pending.enter_context(service.measure(frozen, document, force))
            current = {"measured": measured, "options": candidate, "scope": pending}
            attempts += 1
            if baseline is None:
                baseline = best = current
            pages, error = measured["result"]["pages"], measured["result"]["render_error"]
            if type(pages) is not int or pages < 1 or error:
                status = "unavailable"
                message = error or "无法取得实际页数，已保留原排版。"
                best = baseline
                break
            if pages <= target:
                best = current
                status = "unchanged" if attempts == 1 else "fit"
                message = "当前排版已在预算内。" if attempts == 1 else "已按实际分页调整到预算内。"
                break
            if pages < best["measured"]["result"]["pages"]:
                if best is not baseline:
                    best["scope"].close()
                best = current
            elif current is not baseline:
                pending.close()
        check_document_work()
        preview = service.publish(frozen, best["measured"])
        return {
            "status": status,
            "options": best["options"],
            "pages": preview["pages"],
            "attempts": attempts,
            "preview": preview,
            "message": message,
        }
