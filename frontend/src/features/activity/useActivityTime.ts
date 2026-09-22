import { useEffect, useState } from "react";

/** 使用本地日历生成当天边界，避免 UTC 日期及夏令时偏移 */
export function localDayRange(now = new Date()) {
  const date = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
  return { since: `${date}T00:00`, until: `${date}T23:59:59.999` };
}

/** 对齐日志的 UTC 整秒格式，保留恰好位于本地零点的记录 */
export function activityQueryTime(value: string) {
  return new Date(value).toISOString().replace(/\.000Z$/, "+00:00");
}

/** 默认跟随本地今天，手动修改时间后保留自定义范围 */
export function useActivityTime() {
  const [today, setToday] = useState(true);
  const [day, setDay] = useState(() => localDayRange());
  const [custom, setCustom] = useState({ since: "", until: "" });
  const range = today ? day : custom;
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    /** 到本地零点或重新进入页面时更新日期 */
    function updateDay() {
      const next = localDayRange();
      setDay((current) => (current.since === next.since ? current : next));
      clearTimeout(timer);
      timer = setTimeout(
        updateDay,
        Math.max(50, new Date(next.until).getTime() - Date.now() + 1),
      );
    }
    updateDay();
    document.addEventListener("visibilitychange", updateDay);
    window.addEventListener("focus", updateDay);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", updateDay);
      window.removeEventListener("focus", updateDay);
    };
  }, []);

  /** 修改单个边界时保留另一个边界并退出今天模式 */
  function change(key: "since" | "until", value: string) {
    setCustom({ ...range, [key]: value });
    setToday(false);
  }

  /** 恢复今天范围，立即读取当前本地日期 */
  function showToday() {
    setDay(localDayRange());
    setToday(true);
  }

  /** 清除时间范围以便查看全部历史或跨日关联请求 */
  function clear() {
    setCustom({ since: "", until: "" });
    setToday(false);
  }

  return { ...range, today, change, showToday, clear };
}
