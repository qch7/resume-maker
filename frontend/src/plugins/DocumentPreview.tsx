import { useState, type ReactNode } from "react";
import type { DocumentPreviewProps } from "./documents";
import { clientExtensions } from "./extensions";
import PluginBoundary from "./PluginBoundary";

/** 已有预览和外部组件共用选择入口，卸载后保留输入并显示可用替代项 */
export default function DocumentPreview(
  props: DocumentPreviewProps & {
    preferred?: readonly string[];
    renderLayout?: (selector: ReactNode, preview: ReactNode) => ReactNode;
  },
) {
  const { preferred: preferredIds, renderLayout, ...previewProps } = props;
  const [selected, setSelected] = useState("");
  const entries = clientExtensions.previewers({
    format: props.format,
    input: props.input,
  });
  const preferred = preferredIds
    ?.map((id) => entries.find((item) => item.id === id && item.available))
    .find(Boolean);
  const current =
    entries.find((item) => item.id === selected) ??
    preferred ??
    entries.find((item) => item.available);
  const selector = entries.length > 1 && (
    <label className="document-preview-selector">
      预览方式{" "}
      <select
        aria-label="预览方式"
        value={current?.id ?? ""}
        onChange={(event) => setSelected(event.target.value)}
      >
        {entries.map((item) => (
          <option key={item.id} value={item.id}>
            {item.value.title}
            {item.available ? "" : "（暂不可用）"}
          </option>
        ))}
      </select>
    </label>
  );
  const preview = !current ? (
    <p className="subtle">没有可用的预览器，已保存的资料和成品仍保留。</p>
  ) : !current.available ? (
    <p role="status">{current.reason || "此预览器暂不可用。"}</p>
  ) : (
    <PluginBoundary key={current.id} owner={current.owner}>
      <current.value.component {...previewProps} />
    </PluginBoundary>
  );
  return renderLayout ? (
    renderLayout(selector, preview)
  ) : (
    <div>
      {selector}
      {preview}
    </div>
  );
}
