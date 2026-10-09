/** 使用本地日历生成当天边界，避免 UTC 日期及夏令时偏移 */
export function localDayRange(now = new Date()) {
  const date = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
  return { since: `${date}T00:00`, until: `${date}T23:59:59.999` };
}
