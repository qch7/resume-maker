import type { Resume, Revision } from "../../shared/types/index.ts";

/** 序列化当前实际显示的资料，缺失版本时等待加载；方案名称不影响排版缓存。 */
export function templatePreviewInput(
  draft: Resume,
  revisions: Record<string, Revision>,
  sources: Record<string, Revision>,
): string | null {
  if (!draft.document) return null;
  const items = [];
  for (const item of draft.items) {
    const revision = sources[item.project_id] ?? revisions[item.revision_id];
    if (!revision || !revisions[item.revision_id]) return null;
    const content = revision.content;
    items.push({
      ...item,
      content,
      highlight_ids: content.highlights
        .filter(
          /* 与编辑视图保持相同的亮点顺序和可见范围。 */ (point) =>
            item.highlight_ids.includes(point.id),
        )
        .map(/* 提取工作副本中仍然存在的选中亮点。 */ (point) => point.id),
    });
  }
  return JSON.stringify({
    template_id: draft.template_id,
    document: draft.document,
    items,
  });
}
