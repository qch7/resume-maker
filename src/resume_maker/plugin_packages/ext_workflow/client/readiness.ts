import type { getProjectWorkflow } from "./projectState";
import {
  getProfileProgress,
  visibleSections,
} from "@resume-maker/plugin-sdk/shared/resume/progress";
import { isHonorSection } from "@resume-maker/plugin-sdk/shared/resume/honors/entry";

export type StepReadiness =
  | "pending"
  | "complete"
  | "ready"
  | "optional"
  | "skipped";

/** 按当前简历引用分类可选栏目，不把未采用的资料库项目算入制作进度 */
export function workflowReadiness(
  input: Parameters<typeof getProjectWorkflow>[0],
  completed: boolean[],
): StepReadiness[] {
  const states: StepReadiness[] = completed.map((done) =>
    done ? "complete" : "pending",
  );
  const document = input.draft.document;
  const visible = visibleSections(document);
  const profile = getProfileProgress(document);
  states[0] = completed[0] ? "ready" : "pending";
  const projectsHidden =
    !!document && !visible.some((section) => section.kind === "projects");
  const honorsHidden = !!document && !visible.some(isHonorSection);
  const activeIncluded = input.draft.items.some(
    (item) => item.project_id === input.detail?.project.id,
  );
  const projectsReady =
    input.draft.items.length > 0 &&
    input.draft.items.every((item) => {
      const content = input.revisions[item.revision_id]?.content;
      return (
        content &&
        (!!content.description.trim() ||
          content.highlights.some(
            (point) => point.title.trim() && point.text.trim(),
          ))
      );
    }) &&
    (!activeIncluded || completed[2]);
  states[2] = projectsHidden
    ? "skipped"
    : !input.draft.items.length
      ? "optional"
      : projectsReady
        ? "complete"
        : "pending";
  states[3] = profile.selectedHonor
    ? "complete"
    : honorsHidden
      ? "skipped"
      : "optional";
  return states;
}

/** 分开统计实际完成、可直接使用、可选及明确隐藏的栏目 */
export function readinessCounts(states: StepReadiness[]) {
  return {
    complete: states.filter((state) => state === "complete").length,
    ready: states.filter((state) => state === "ready").length,
    optional: states.filter((state) => state === "optional").length,
    skipped: states.filter((state) => state === "skipped").length,
  };
}

export const READINESS_LABELS: Record<StepReadiness, string> = {
  pending: "待完成",
  complete: "已完成",
  ready: "已选择 · 可直接使用",
  optional: "可跳过",
  skipped: "已跳过",
};
