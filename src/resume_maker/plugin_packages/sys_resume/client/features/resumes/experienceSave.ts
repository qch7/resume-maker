import type {
  Resume,
  Revision,
} from "@resume-maker/plugin-sdk/shared/types/index";
import { orderedHighlightIds } from "@resume-maker/plugin-sdk/shared/resume/composition";

/** 仅向原方案仍保留的项目引用应用已保存版本，保留请求期间的其他输入 */
export function applyExperienceRevision(
  current: Resume,
  submitted: Resume,
  revision: Revision,
): Resume {
  if (
    current.id !== submitted.id ||
    (!current.id &&
      (!submitted.draft_id || current.draft_id !== submitted.draft_id))
  )
    return current;
  const previous = submitted.items.find(
    (item) => item.project_id === revision.project_id,
  );
  const latest = current.items.find(
    (item) => item.project_id === revision.project_id,
  );
  if (latest?.revision_id !== previous?.revision_id) return current;
  const item = {
    ...latest,
    project_id: revision.project_id,
    revision_id: revision.id,
    highlight_ids: !latest
      ? revision.content.highlights.map((point) => point.id)
      : orderedHighlightIds(revision.content.highlights, latest.highlight_ids),
  };
  return {
    ...current,
    items: latest
      ? current.items.map((value) =>
          value.project_id === revision.project_id ? item : value,
        )
      : [...current.items, item],
  };
}
