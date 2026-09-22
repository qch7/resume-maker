export const DEFAULT_POLLING_PATHS =
  "/api/state\n/api/honors\n/api/templates/analyses/*/progress";
export const DEFAULT_ACTIVITY_PREFERENCES = {
  hidePolling: true,
  hideMaintenance: true,
  pollingPaths: DEFAULT_POLLING_PATHS,
  overviewHeight: 160,
  detailWidth: 460,
  detailHeight: 280,
};
export type ActivityPreferences = typeof DEFAULT_ACTIVITY_PREFERENCES;

/** 校验本地缓存并补齐新增设置，损坏值不会破坏日志布局 */
export function restoreActivityPreferences(
  value: Partial<ActivityPreferences> | null,
) {
  const result = { ...DEFAULT_ACTIVITY_PREFERENCES };
  if (typeof value?.hidePolling === "boolean")
    result.hidePolling = value.hidePolling;
  if (typeof value?.hideMaintenance === "boolean")
    result.hideMaintenance = value.hideMaintenance;
  if (
    typeof value?.pollingPaths === "string" &&
    value.pollingPaths.length <= 2000
  )
    result.pollingPaths = value.pollingPaths;
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

/** 检查每行轮询路径，只将星号当作通配符 */
export function pollingPathError(value: string) {
  if (value.length > 2000) return "路径总长度不能超过 2,000 字符";
  return value
    .split("\n")
    .some((line) => line.trim() && !/^\/api\/[^\s?#]*$/.test(line.trim()))
    ? "每行填写 /api/ 开头的路径，可用 * 匹配，不含查询参数"
    : "";
}
