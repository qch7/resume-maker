import type { Conversation, Project } from "../../shared/types/index";

export type SidebarSort = "recent" | "asc" | "desc";
const names = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});
/** 把有效日期转换为排序时间戳，缺失或无效日期按零处理。 */
const timestamp = (value?: string) => Date.parse(value ?? "") || 0;

/** 校验缓存的排序模式，未知值回退为最近修改。 */
export function restoreSidebarSort(value: unknown): SidebarSort {
  return value === "asc" || value === "desc" ? value : "recent";
}

/** 导航到子项目时展开其祖先分组，保留其他项目的折叠偏好。 */
export function expandProjectPath(
  projects: Project[],
  id: string,
  folded: Record<string, boolean>,
) {
  const next = { ...folded };
  const visited = new Set<string>();
  let current: string | null | undefined = id;
  while (current && !visited.has(current)) {
    visited.add(current);
    next[current] = false;
    current = projects.find(
      /* 查找当前层级所属的整体项目。 */ (p) => p.id === current,
    )?.parent_id;
  }
  return next;
}

/** 聚合项目与会话活动时间，按最近修改或自然名称稳定排序。 */
export function sortSidebar(
  projects: Project[],
  conversations: Conversation[],
  mode: SidebarSort,
) {
  const activity = new Map(
    projects.map(
      /* 逐项转换数据，保留当前业务需要的字段。 */ (p) => [
        p.id,
        Math.max(timestamp(p.updated_at), timestamp(p.activity_at)),
      ],
    ),
  );
  for (const conversation of conversations) {
    activity.set(
      conversation.project_id,
      Math.max(
        activity.get(conversation.project_id) ?? 0,
        timestamp(conversation.updated_at),
      ),
    );
  }
  const byId = new Map(
    projects.map(
      /* 建立父子查找表，使整体项目继承子项目的最近活动时间。 */ (p) => [
        p.id,
        p,
      ],
    ),
  );
  for (const project of projects) {
    const visited = new Set([project.id]);
    let parentId = project.parent_id;
    while (parentId && byId.has(parentId) && !visited.has(parentId)) {
      visited.add(parentId);
      activity.set(
        parentId,
        Math.max(activity.get(parentId) ?? 0, activity.get(project.id) ?? 0),
      );
      parentId = byId.get(parentId)?.parent_id;
    }
  }
  /** 按所选模式比较条目，同名同时间时以稳定标识保证顺序确定。 */
  function compare(
    a: { id: string },
    b: { id: string },
    nameA: string,
    nameB: string,
    timeA: number,
    timeB: number,
  ) {
    return (
      (mode === "recent" ? timeB - timeA : 0) ||
      names.compare(nameA, nameB) * (mode === "desc" ? -1 : 1) ||
      a.id.localeCompare(b.id)
    );
  }
  return {
    projects: [...projects].sort(
      /* 使用稳定比较规则排列条目，避免修改输入列表。 */ (a, b) =>
        compare(
          a,
          b,
          a.name,
          b.name,
          activity.get(a.id) ?? 0,
          activity.get(b.id) ?? 0,
        ),
    ),
    conversations: [...conversations].sort(
      /* 使用稳定比较规则排列条目，避免修改输入列表。 */ (a, b) =>
        compare(
          a,
          b,
          a.title,
          b.title,
          timestamp(a.updated_at),
          timestamp(b.updated_at),
        ),
    ),
  };
}
