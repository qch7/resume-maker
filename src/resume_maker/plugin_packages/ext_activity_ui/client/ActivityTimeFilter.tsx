import { useEffect, useRef, useState } from "react";
import { CalendarDays, ChevronDown, X } from "lucide-react";
import type { useActivityTime } from "./useActivityTime";

/** 在筛选按钮旁展开时间范围，保持工具栏高度固定 */
export default function ActivityTimeFilter({
  time,
}: {
  time: ReturnType<typeof useActivityTime>;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    /** 点击时间弹层外部时收起，原生日期选择器仍可操作 */
    function closeOutside(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node))
        setOpen(false);
    }
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);
  return (
    <div
      className="activity-time-filter"
      ref={root}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      <button
        ref={trigger}
        aria-label="时间筛选"
        aria-expanded={open}
        className={time.since || time.until ? "active" : ""}
        title={
          time.today
            ? "本地今天"
            : `${time.since || "不限"} 至 ${time.until || "不限"}`
        }
        onClick={() => setOpen(!open)}
      >
        <CalendarDays size={14} />
        {time.today
          ? "今天"
          : time.since || time.until
            ? "自定义时间"
            : "全部时间"}
        <ChevronDown size={12} />
      </button>
      {open && (
        <div
          className="activity-time-popover"
          role="dialog"
          aria-label="时间范围"
        >
          <div className="row">
            <button
              className={time.today ? "active" : ""}
              onClick={() => {
                time.showToday();
                setOpen(false);
              }}
            >
              今天
            </button>
            <button
              onClick={() => {
                time.clear();
                setOpen(false);
              }}
            >
              全部时间
            </button>
            <button
              className="activity-time-close"
              aria-label="关闭时间筛选"
              onClick={() => setOpen(false)}
            >
              <X size={14} />
            </button>
          </div>
          <label>
            从
            <input
              type="datetime-local"
              step="0.001"
              aria-label="开始时间"
              value={time.since}
              onChange={(event) => time.change("since", event.target.value)}
            />
          </label>
          <label>
            至
            <input
              type="datetime-local"
              step="0.001"
              aria-label="结束时间"
              value={time.until}
              onChange={(event) => time.change("until", event.target.value)}
            />
          </label>
        </div>
      )}
    </div>
  );
}
