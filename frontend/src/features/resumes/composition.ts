import type { Export, Highlight, Resume, Revision } from "../../shared/types";
import { sameResumeDocument } from "../profile/comparison.ts";

/** 将亮点选择投影到经历版本的顺序；勾选先后不参与排序 */
export function orderedHighlightIds(
  highlights: Highlight[],
  selectedIds: string[],
) {
  const selected = new Set(selectedIds);
  return highlights
    .filter(/* 只保留已经勾选的亮点 */ (h) => selected.has(h.id))
    .map(/* 沿用经历中的稳定顺序 */ (h) => h.id);
}

/** 切换亮点后恢复经历顺序；重新勾选回到原位置 */
export function toggleHighlightSelection(
  highlights: Highlight[],
  selectedIds: string[],
  id: string,
) {
  const next = selectedIds.includes(id)
    ? selectedIds.filter(/* 移除本次取消勾选的亮点 */ (value) => value !== id)
    : [...selectedIds, id];
  return orderedHighlightIds(highlights, next);
}

/** 固定引用始终按版本顺序导出；未提交亮点的选择暂存到正式条目之后 */
export function orderCompositionHighlights(
  draft: Resume,
  revisions: Record<string, Revision>,
): Resume {
  return {
    ...draft,
    items: draft.items.map(
      /* 编辑区可单独排序；取消草稿后组合仍须恢复固定版本的顺序 */ (item) => {
        const highlights = revisions[item.revision_id]?.content.highlights;
        if (!highlights) return item;
        const positions = new Map(
          highlights.map(
            /* 记录正式版本中的位置 */ (point, index) => [point.id, index],
          ),
        );
        return {
          ...item,
          highlight_ids: [...item.highlight_ids].sort(
            /* 暂存的新亮点保持相对顺序且不因版本尚未提交而丢失选择 */ (a, b) =>
              (positions.get(a) ?? highlights.length) -
              (positions.get(b) ?? highlights.length),
          ),
        };
      },
    ),
  };
}

/** 比较实际组合内容和固定引用；忽略保存次数等非内容变化 */
export function sameComposition(a: Resume | undefined, b: Resume) {
  return (
    !!a &&
    a.id === b.id &&
    a.name === b.name &&
    a.template_id === b.template_id &&
    JSON.stringify(a.items) === JSON.stringify(b.items) &&
    sameResumeDocument(a.document, b.document)
  );
}

/** 确认导出属于当前简历且清单中的组合与当前选择一致 */
export function isCurrentExport(result: Export | null, draft: Resume) {
  return (
    !!result &&
    result.resume_id === draft.id &&
    sameComposition(result.manifest?.resume, draft)
  );
}

/** 保存请求返回时保留后续输入或已切换的方案且只推进同一方案的服务器版本号 */
export function acceptSavedComposition(
  current: Resume,
  submitted: Resume,
  saved: Resume,
): Resume {
  if (current.id !== submitted.id) return current;
  return sameComposition(current, submitted)
    ? saved
    : { ...current, id: saved.id, version: saved.version };
}
