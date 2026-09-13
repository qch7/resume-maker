import type { Export, Highlight, Resume, Revision } from "../../shared/types";

/** 将亮点选择投影到经历版本的顺序，勾选先后不参与排序。 */
export function orderedHighlightIds(
  highlights: Highlight[],
  selectedIds: string[],
) {
  const selected = new Set(selectedIds);
  return highlights
    .filter(/* 只保留已经勾选的亮点。 */ (h) => selected.has(h.id))
    .map(/* 沿用经历中的稳定顺序。 */ (h) => h.id);
}

/** 切换亮点后恢复经历顺序，重新勾选回到原位置。 */
export function toggleHighlightSelection(
  highlights: Highlight[],
  selectedIds: string[],
  id: string,
) {
  const next = selectedIds.includes(id)
    ? selectedIds.filter(/* 移除本次取消勾选的亮点。 */ (value) => value !== id)
    : [...selectedIds, id];
  return orderedHighlightIds(highlights, next);
}

/** 修正历史组合中的勾选顺序；只使用固定版本，不改变项目顺序。 */
export function normalizeHighlightOrder(
  draft: Resume,
  revisions: Record<string, Revision>,
) {
  let changed = false;
  const items = draft.items.map(
    /* 按各项目固定引用的版本整理亮点。 */ (item) => {
      const revision = revisions[item.revision_id];
      // 版本缓存异步到达前保留全部选择，避免加载过程清空草稿。
      if (!revision) return item;
      const highlight_ids = orderedHighlightIds(
        revision.content.highlights,
        item.highlight_ids,
      );
      // 新增草稿亮点尚无正式引用，保留其本机选择，提交后再归入版本顺序。
      const valid = new Set(
        revision.content.highlights.map(
          /* 收集正式版本已有条目。 */ (point) => point.id,
        ),
      );
      highlight_ids.push(
        ...item.highlight_ids.filter(
          /* 暂存未提交条目的选择。 */ (id) => !valid.has(id),
        ),
      );
      if (
        highlight_ids.length === item.highlight_ids.length &&
        highlight_ids.every(
          /* 顺序未变时复用对象，避免产生无意义的状态更新。 */ (id, index) =>
            id === item.highlight_ids[index],
        )
      )
        return item;
      changed = true;
      return { ...item, highlight_ids };
    },
  );
  return changed ? { ...draft, items } : draft;
}

/** 比较实际组合内容和固定引用，忽略保存次数等非内容变化。 */
export function sameComposition(a: Resume | undefined, b: Resume) {
  return (
    !!a &&
    a.id === b.id &&
    a.name === b.name &&
    a.template_id === b.template_id &&
    JSON.stringify(a.items) === JSON.stringify(b.items)
  );
}

/** 确认导出属于当前简历且清单中的组合与当前选择一致。 */
export function isCurrentExport(result: Export | null, draft: Resume) {
  return (
    !!result &&
    result.resume_id === draft.id &&
    sameComposition(result.manifest?.resume, draft)
  );
}
