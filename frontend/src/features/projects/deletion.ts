import type { Job, Project, Resume } from "../../shared/types/index";

/** 收集项目及全部后代；整组删除与占用检查使用相同范围 */
export function projectDeletionIds(projects: Project[], projectId: string) {
  const ids = new Set([projectId]);
  for (const id of ids) {
    for (const project of projects) {
      if (project.parent_id === id) ids.add(project.id);
    }
  }
  return ids;
}

/** 已保存简历与当前未保存组合都阻止删除；隐藏项目同样保留引用 */
export function projectDeletionBlocker(
  ids: Set<string>,
  resumes: Resume[],
  draft: Resume,
  jobs: Job[],
) {
  const used = resumes.filter((resume) =>
    resume.items.some((item) => ids.has(item.project_id)),
  );
  if (used.length) {
    const names = used
      .slice(0, 3)
      .map((resume) => `“${resume.name}”`)
      .join("、");
    return `项目或其子项目正在被 ${used.length} 份简历使用（${names}），不能删除。请先从这些简历中移除项目并保存组合。`;
  }
  if (draft.items.some((item) => ids.has(item.project_id)))
    return "项目或其子项目已加入当前简历，不能删除。请先取消勾选，并保存已有简历的组合。";
  if (
    jobs.some(
      (job) =>
        ids.has(job.project_id) && ["queued", "running"].includes(job.status),
    )
  )
    return "项目或其子项目仍有 AI 任务进行中，请等待完成或取消后再删除。";
  return "";
}
