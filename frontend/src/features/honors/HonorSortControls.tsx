import {
  ArrowDown,
  ArrowUp,
  CalendarDays,
  CaseSensitive,
  Clock3,
} from "lucide-react";
import { nextHonorSort, type HonorSort, type HonorSortKey } from "./sort";

const OPTIONS = [
  { key: "recent", label: "更新时间", icon: Clock3 },
  { key: "date", label: "获得日期", icon: CalendarDays },
  { key: "name", label: "名称", icon: CaseSensitive },
] as const;

/** 三个紧凑图标各自切换正倒序，通过箭头、高亮及提示说明当前排序 */
export default function HonorSortControls({
  value,
  onChange,
  label = "荣誉排序",
  disabled = false,
}: {
  value: HonorSort | null;
  onChange: (value: HonorSort) => void;
  label?: string;
  disabled?: boolean;
}) {
  /** 名称用字母方向，日期用新旧方向，使提示不依赖用户理解升降序 */
  function directionLabel(
    key: HonorSortKey,
    direction: HonorSort["direction"],
  ) {
    return key === "name"
      ? direction === "asc"
        ? "A → Z"
        : "Z → A"
      : direction === "asc"
        ? "旧到新"
        : "新到旧";
  }
  return (
    <div className="honor-sort-controls" role="group" aria-label={label}>
      {OPTIONS.map(
        /* 每个维度只有一个按钮，重复点击即可反向排列 */ ({
          key,
          label: name,
          icon: Icon,
        }) => {
          const active = value?.key === key;
          const next = nextHonorSort(value, key);
          const direction = active ? value.direction : next.direction;
          const description = active
            ? `按${name}排序：${directionLabel(key, direction)}；点击切换为${directionLabel(key, next.direction)}`
            : `按${name}排序：${directionLabel(key, next.direction)}`;
          const Arrow = direction === "asc" ? ArrowUp : ArrowDown;
          return (
            <button
              key={key}
              type="button"
              className="icon-button"
              aria-label={description}
              title={description}
              aria-pressed={active}
              disabled={disabled}
              onClick={
                /* 只有明确点击才调整排序，轮询不改变简历顺序 */ () =>
                  onChange(next)
              }
            >
              <Icon size={16} aria-hidden="true" />
              <Arrow size={11} aria-hidden="true" />
            </button>
          );
        },
      )}
    </div>
  );
}
