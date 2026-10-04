import type { useDocumentImporters } from "../hooks/useDocumentImporters";

/** 在原有导入流程中选择处理器，缺失的旧选择不会自动变成其他插件 */
export default function ImporterSelect({
  value,
  disabled = false,
}: {
  value: ReturnType<typeof useDocumentImporters>;
  disabled?: boolean;
}) {
  return (
    <label className="importer-select">
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
            {item.title} · {item.owner}
          </option>
        ))}
      </select>
      <small role="status">
        {value.loading
          ? "正在读取可用格式…"
          : value.error ||
            (value.missing
              ? "请重新选择处理器，或启用原插件。"
              : value.extensions.length
                ? `支持：${value.extensions.join("、")}`
                : "尚未启用文件导入插件，可以继续手动填写。")}
      </small>
    </label>
  );
}
