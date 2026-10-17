import { useContext, type CSSProperties, type ReactNode } from "react";
import { LayoutSelectionContext } from "./layoutSelection";

/** 保留原有文字样式及语义标签，在可编辑内容预览中提供点选入口 */
export default function LayoutText({
  as: Tag = "p",
  layoutKey,
  className,
  style,
  children,
}: {
  as?: "h1" | "h2" | "h3" | "p" | "li" | "span";
  layoutKey?: string;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  const selection = useContext(LayoutSelectionContext);
  return (
    <Tag className={className} style={style}>
      {selection && layoutKey ? (
        <button
          type="button"
          className="content-layout-target"
          data-layout-key={layoutKey}
          aria-pressed={selection.key === layoutKey}
          title="点击调整这项文字的样式"
          onClick={() => selection.select(layoutKey)}
        >
          {children}
        </button>
      ) : (
        children
      )}
    </Tag>
  );
}
