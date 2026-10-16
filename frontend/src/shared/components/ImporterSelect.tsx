import { useState } from "react";
import type { useDocumentImporters } from "../hooks/useDocumentImporters";

/** 默认自动识别，按需展开技术选项，缺失的旧选择仍保留并明确提示 */
export default function ImporterSelect({
  value,
  disabled = false,
  compact = false,
}: {
  value: ReturnType<typeof useDocumentImporters>;
  disabled?: boolean;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(!!value.selected);
  const selected = value.items.find((item) => item.id === value.selected);
  const attention = !!value.conflict || (!value.loading && value.missing);
  return (
    <div className={`importer-select ${compact ? "compact" : ""}`}>
      <span className="importer-summary">
        文件处理：
        {value.selected ? (selected?.title ?? "原选择不可用") : "自动识别"}
      </span>
      <details
        className="importer-advanced"
        open={expanded || attention}
        onToggle={(event) => setExpanded(event.currentTarget.open)}
      >
        <summary>高级处理设置</summary>
        <label>
          文件处理方式
          <select
            value={value.selected}
            disabled={disabled || value.loading}
            onChange={(event) => value.setSelected(event.target.value)}
          >
            <option value="">自动识别（有冲突时提示选择）</option>
            {value.missing && (
              <option value={value.selected}>所选处理器已不可用</option>
            )}
            {value.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title} · {item.id}
              </option>
            ))}
          </select>
        </label>
      </details>
      {(value.conflict ||
        !compact ||
        value.loading ||
        value.error ||
        value.missing ||
        !value.extensions.length) && (
        <small role="status">
          {value.conflict ||
            (value.loading
              ? "正在读取可用格式…"
              : value.error ||
                (value.missing
                  ? "请重新选择处理器，或启用原插件。"
                  : value.extensions.length
                    ? `支持：${value.extensions.join("、")}`
                    : "尚未启用文件导入插件，可以继续手动填写。"))}
        </small>
      )}
    </div>
  );
}
