import type { Conversation, Project } from "./types";

export type SidebarSort = "recent" | "asc" | "desc";
const names = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});
const timestamp = (value?: string) => Date.parse(value ?? "") || 0;

export function restoreSidebarSort(value: unknown): SidebarSort {
  return value === "asc" || value === "desc" ? value : "recent";
}

export function sortSidebar(
  projects: Project[],
  conversations: Conversation[],
  mode: SidebarSort,
) {
  const activity = new Map(
    projects.map((p) => [
      p.id,
      Math.max(timestamp(p.updated_at), timestamp(p.activity_at)),
    ]),
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
    projects: [...projects].sort((a, b) =>
      compare(
        a,
        b,
        a.name,
        b.name,
        activity.get(a.id) ?? 0,
        activity.get(b.id) ?? 0,
      ),
    ),
    conversations: [...conversations].sort((a, b) =>
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
