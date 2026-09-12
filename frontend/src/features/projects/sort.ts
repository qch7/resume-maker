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
