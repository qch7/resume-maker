import type { MappingReview } from "./types.ts";
import { targetLabel } from "./visual.ts";

export interface TemplateProblem {
  message: string;
  nodes: string[];
}

/** 合并全部阻止使用的问题，保留定位信息，避免空 issues 隐藏试填错误。 */
export function reviewProblems(
  review: MappingReview | null,
): TemplateProblem[] {
  if (!review || review.ready) return [];
  const problems = new Map<string, TemplateProblem>();
  for (const issue of review.issues ?? [])
    problems.set(issue.message, { ...issue, nodes: [...issue.nodes] });
  for (const message of review.errors)
    if (!problems.has(message)) problems.set(message, { message, nodes: [] });
  for (const target of review.missing ?? []) {
    const message = `“${targetLabel(target)}”尚未安排填写位置`;
    problems.set(message, { message, nodes: [] });
  }
  for (const node of review.unresolved) {
    problems.set(`unresolved:${node.id}`, {
      message:
        node.kind === "image"
          ? "图片用途尚未确认"
          : `原文用途尚未确认：${node.text || "空白段落"}`,
      nodes: [node.id],
    });
  }
  return problems.size
    ? [...problems.values()]
    : [{ message: "模板检查尚未通过，请让 AI 继续检查并修复", nodes: [] }];
}

/** 在固定操作区展示首个具体原因，多项问题引导用户查看完整列表。 */
export function reviewProblemSummary(problems: TemplateProblem[]) {
  if (!problems.length) return "";
  return `${problems[0].message}${problems.length > 1 ? `（共 ${problems.length} 项问题）` : ""}`;
}
