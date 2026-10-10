export const DEFAULT_ACTIVITY_PREFERENCES = {
  hidePolling: true,
  showStarts: false,
  hiddenRules: "",
  overviewHeight: 136,
  detailWidth: 460,
  detailHeight: 280,
};
export type ActivityPreferences = typeof DEFAULT_ACTIVITY_PREFERENCES;
export type SavedActivityPreferences = Partial<
  Omit<ActivityPreferences, "hiddenRules">
> & { rulesOverride?: string };

/** 校验本地缓存并补齐新增设置，损坏值不会破坏日志布局 */
export function restoreActivityPreferences(
  value: SavedActivityPreferences | null,
  defaultRules = "",
) {
  const result = { ...DEFAULT_ACTIVITY_PREFERENCES, hiddenRules: defaultRules };
  if (typeof value?.hidePolling === "boolean")
    result.hidePolling = value.hidePolling;
  if (typeof value?.showStarts === "boolean")
    result.showStarts = value.showStarts;
  if (
    typeof value?.rulesOverride === "string" &&
    !hiddenRuleError(value.rulesOverride)
  ) {
    result.hiddenRules = value.rulesOverride;
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
