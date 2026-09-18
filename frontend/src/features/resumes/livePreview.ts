import type { Experience, Resume, Revision } from "../../shared/types/index";
import { experienceContent } from "../experiences/visibility.ts";

/** 使用正在编辑的工作副本构建预览且不改写组合引用或不可变修订缓存 */
export function buildLivePreview(
  draft: Resume,
  revisions: Record<string, Revision>,
  working: Record<string, Experience>,
  activeProject: string,
  revisionId: string,
) {
  const sources: Record<string, Revision> = {};
  let changed = false;
  for (const item of draft.items) {
    const pinned = revisions[item.revision_id];
    const editing = revisions[revisionId];
    const source =
      item.project_id === activeProject &&
      editing?.project_id === item.project_id
        ? editing
        : pinned;
    if (!source) continue;
    const content = working[source.id] ?? source.content;
    const settings =
      draft.document?.project_visibility?.[item.project_id] ?? {};
    sources[item.project_id] =
      content === source.content ? source : { ...source, content };
    if (
      source.id !== item.revision_id ||
      experienceContent(content, settings) !==
        experienceContent(pinned?.content, settings) ||
      item.highlight_ids.some(
        /* 新增草稿亮点必须先进入正式版本；才能保存或导出固定引用 */ (id) =>
          !pinned?.content.highlights.some(
            /* 校验组合引用的亮点归属 */ (point) => point.id === id,
          ),
      )
    )
      changed = true;
  }
  return { sources, changed };
}
