import type { State } from "@resume-maker/plugin-sdk/shared/types/index";

export type WorkspaceArea =
  | "projects"
  | "personal"
  | "structure"
  | "templates"
  | "honors"
  | "recruitment";

export interface WorkspaceLocation {
  area: WorkspaceArea;
  page: string;
  projectId: string;
  revisionId: string;
  mode: "edit" | "chat";
  conversationId: string;
}

export const DEFAULT_LOCATION: WorkspaceLocation = {
  area: "projects",
  page: "",
  projectId: "",
  revisionId: "",
  mode: "edit",
  conversationId: "",
};

const PARAMETERS = {
  area: "workspace",
  page: "page",
  projectId: "project",
  revisionId: "revision",
  mode: "view",
  conversationId: "conversation",
} as const;

/** 地址包含工作区参数时优先采用地址，否则恢复本页上次位置 */
export function readWorkspaceLocation(
  href: string,
  saved: unknown,
): WorkspaceLocation {
  const params = new URL(href).searchParams;
  const fromUrl = Object.values(PARAMETERS).some((key) => params.has(key));
  const source =
    saved && typeof saved === "object"
      ? (saved as Record<string, unknown>)
      : {};
  /** 限制地址及缓存字段的类型、长度 */
  const value = (key: keyof WorkspaceLocation) => {
    const result = fromUrl ? params.get(PARAMETERS[key]) : source[key];
    return typeof result === "string" && result.length <= 300 ? result : "";
  };
  return {
    area: (value("area") || "projects") as WorkspaceArea,
    page: value("page"),
    projectId: value("projectId"),
    revisionId: value("revisionId"),
    mode: value("mode") === "chat" ? "chat" : "edit",
    conversationId: value("conversationId"),
  };
}

/** 只更新工作区导航参数，保留地址中其他参数及片段 */
export function workspaceUrl(href: string, location: WorkspaceLocation) {
  const url = new URL(href);
  for (const [key, parameter] of Object.entries(PARAMETERS)) {
    const value = location[key as keyof WorkspaceLocation];
    if (value && !(key === "mode" && value === "edit"))
      url.searchParams.set(parameter, value);
    else url.searchParams.delete(parameter);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/** 拒绝失效项目、跨项目会话及缺失插件，正文仍由原草稿流程恢复 */
export function normalizeWorkspaceLocation(
  requested: WorkspaceLocation,
  state: Pick<State, "projects" | "conversations">,
  areas: readonly WorkspaceArea[],
  pages: readonly string[],
  chatAvailable: boolean,
  defaultProjectId: string,
): WorkspaceLocation {
  const project =
    state.projects.find((item) => item.id === requested.projectId) ??
    state.projects.find((item) => item.id === defaultProjectId);
  const sameProject = project?.id === requested.projectId;
  const conversation =
    state.conversations.find(
      (item) =>
        item.id === requested.conversationId && item.project_id === project?.id,
    ) ?? state.conversations.find((item) => item.project_id === project?.id);
  const page = pages.includes(requested.page) ? requested.page : "";
  const mode =
    chatAvailable && conversation && requested.mode === "chat"
      ? "chat"
      : "edit";
  return {
    area: page
      ? "projects"
      : areas.includes(requested.area)
        ? requested.area
        : "projects",
    page,
    projectId: project?.id ?? "",
    revisionId:
      (sameProject && requested.revisionId) || project?.head_revision || "",
    mode,
    conversationId: mode === "chat" ? (conversation?.id ?? "") : "",
  };
}

/** 同一工作区、项目、会话各自保留滚动，版本保存不改变位置归属 */
export function workspaceScrollKey(location: WorkspaceLocation) {
  return JSON.stringify([
    location.area,
    location.page,
    location.projectId,
    location.mode,
    location.conversationId,
  ]);
}
