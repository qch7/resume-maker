import type { Export, Resume } from "../../shared/types";

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
