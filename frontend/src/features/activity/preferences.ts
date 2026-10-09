export const DEFAULT_POLLING_PATHS =
  "/api/state\n/api/honors\n/api/templates/analyses/*/progress";
const PREVIOUS_HIDDEN_RULES = `${DEFAULT_POLLING_PATHS}\ntemplate_library.purge_expired`;
export const DEFAULT_HIDDEN_RULES = [
  DEFAULT_POLLING_PATHS,
  "GET /api/templates/analyses/*",
  "POST /api/templates/analyses/*/review",
  "template_library.purge_expired",
  "template_library.state",
  "workspace.state",
  "catalog.project",
  "catalog.revision",
  "catalog.template",
  "catalog.conversation",
  "catalog.working",
  "templates.get",
  "templates.source",
  "templates.projects",
  "templates.progress",
  "honors.get",
  "honors.list",
  "honors.file",
  "conversations.archived_conversations",
  "conversations.get_conversation",
  "ai:thread.started",
  "ai:turn.started",
].join("\n");
export const DEFAULT_ACTIVITY_PREFERENCES = {
  hidePolling: true,
  hiddenRules: DEFAULT_HIDDEN_RULES,
  overviewHeight: 136,
  detailWidth: 460,
  detailHeight: 280,
};
export type ActivityPreferences = typeof DEFAULT_ACTIVITY_PREFERENCES;
export type SavedActivityPreferences = Partial<ActivityPreferences> & {
  pollingPaths?: string;
  hideMaintenance?: boolean;
};

/** 校验本地缓存并补齐新增设置，损坏值不会破坏日志布局 */
export function restoreActivityPreferences(
  value: SavedActivityPreferences | null,
) {
  const result = { ...DEFAULT_ACTIVITY_PREFERENCES };
  if (typeof value?.hidePolling === "boolean")
    result.hidePolling = value.hidePolling;
  if (
    typeof value?.hiddenRules === "string" &&
    !hiddenRuleError(value.hiddenRules)
  ) {
    result.hiddenRules =
      value.hiddenRules.trim() === PREVIOUS_HIDDEN_RULES
        ? DEFAULT_HIDDEN_RULES
        : value.hiddenRules;
  } else {
    const paths =
      typeof value?.pollingPaths === "string" &&
      value.pollingPaths.length <= 2000
        ? value.pollingPaths
        : DEFAULT_POLLING_PATHS;
    const migrated = [
      paths,
      value?.hideMaintenance === false ? "" : "template_library.purge_expired",
    ]
      .filter(Boolean)
      .join("\n");
    result.hiddenRules = !hiddenRuleError(migrated)
      ? migrated
      : value?.hideMaintenance === false
        ? DEFAULT_POLLING_PATHS
        : DEFAULT_HIDDEN_RULES;
    if (migrated === PREVIOUS_HIDDEN_RULES)
      result.hiddenRules = DEFAULT_HIDDEN_RULES;
  }
  for (const key of [
    "overviewHeight",
    "detailWidth",
    "detailHeight",
  ] as const) {
    const size = value?.[key];
    if (typeof size === "number" && Number.isFinite(size))
      result[key] = Math.min(2000, Math.max(32, size));
  }
  return result;
}

/** 检查统一隐藏规则，允许 API 路径和操作名中的星号通配符 */
export function hiddenRuleError(value: string) {
  if (value.length > 4000) return "规则总长度不能超过 4,000 字符";
  const lines = value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (new Set(lines).size > 100) return "最多填写 100 条规则";
  return lines.some(
    (line) =>
      !/^(?:(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) )?\/api\/[^\s?#]*$/.test(
        line,
      ) &&
      !/^(?:ai|task|system|client):[A-Za-z0-9_.*-]+$/.test(line) &&
      !/^[A-Za-z_*][A-Za-z0-9_.*-]*\.[A-Za-z0-9_.*-]+$/.test(line),
  )
    ? "填写 API 路径（可加 GET/POST 等方法）、操作名或 类型:事件，支持 *"
    : "";
}
