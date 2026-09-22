import { useEffect, useRef } from "react";
import { ChevronDown } from "lucide-react";

/** 用可勾选下拉列表组合筛选，未选具体项目时显示全部 */
export default function ActivityMultiSelect({
  label,
  allLabel,
  options,
  value,
  onChange,
}: {
  label: string;
  allLabel: string;
  options: Record<string, string>;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const menu = useRef<HTMLDetailsElement>(null);
  const selected = value.map((key) => options[key]).join("、");
  useEffect(() => {
    /** 点击筛选菜单外部时收起列表 */
    function closeOutside(event: PointerEvent) {
      if (menu.current && !menu.current.contains(event.target as Node))
        menu.current.open = false;
    }
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);
  return (
    <details
      className="activity-multiselect"
      ref={menu}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          event.currentTarget.open = false;
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.currentTarget.open = false;
          event.currentTarget.querySelector("summary")?.focus();
        }
      }}
    >
      <summary
        aria-label={`${label}：${selected || allLabel}`}
        title={selected || allLabel}
      >
        <span>
          {value.length === 0
            ? allLabel
            : value.length === 1
              ? selected
              : `${label.replace("日志", "")} · ${value.length}`}
        </span>
        <ChevronDown size={13} />
      </summary>
      <div
        className="activity-multiselect-menu"
        role="group"
        aria-label={`${label}多选`}
      >
        <button
          type="button"
          className={value.length === 0 ? "active" : ""}
          onClick={() => onChange([])}
        >
          {allLabel}
        </button>
        {Object.entries(options).map(([key, text]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={value.includes(key)}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...value, key]
                    : value.filter((item) => item !== key),
                )
              }
            />
            {text}
          </label>
        ))}
      </div>
    </details>
  );
}
