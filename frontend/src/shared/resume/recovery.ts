import type { Resume, State } from "../types/index.ts";

/** 隔离已删除的项目，保留姓名、栏目及暂不可用插件的模板引用 */
export function recoverResume(draft: Resume, state: State) {
  const items = draft.items.filter((item) =>
    state.projects.some((project) => project.id === item.project_id),
  );
  const deleted =
    !!draft.id && !state.resumes.some((item) => item.id === draft.id);
  const changed = deleted || items.length !== draft.items.length;
  return {
    changed,
    draft: changed
      ? {
          ...draft,
          ...(deleted ? { id: "", version: 0 } : {}),
          items,
        }
      : draft,
  };
}
