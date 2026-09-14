import { useEffect, useMemo, useRef } from "react";
import type { TemplateNode, TemplatePlan } from "./types";
import {
  highlightedText,
  mappingIndex,
  REGION_LABELS,
  targetLabel,
} from "./visual";
import TemplateImage from "./TemplateImage";

interface Props {
  nodes: TemplateNode[];
  plan: TemplatePlan;
  taskId: string;
  selected: string[];
  onSelect: (id: string, extend?: boolean) => void;
  filter: "all" | "unresolved";
}

/** 以可点击的文档结构展示识别结果，字段高亮和表格层级均来自当前映射。 */
export default function TemplateCanvas(props: Props) {
  const root = useRef<HTMLDivElement>(null);
  const tree = useMemo(
    /* 将节点接到最近可见祖先，保留文本框和表格内部层级。 */ () => {
      const children = new Map<string, TemplateNode[]>();
      for (const node of props.nodes) {
        const parent = node.ancestors[0] ?? node.part;
        children.set(parent, [...(children.get(parent) ?? []), node]);
      }
      return children;
    },
    [props.nodes],
  );
  const mappings = useMemo(
    /* 一次计算当前映射的显示状态，避免递归时重复遍历。 */ () =>
      mappingIndex(props.nodes, props.plan),
    [props.nodes, props.plan],
  );
  const parts = [
    ...new Set(
      props.nodes.map(/* 提取各 Word 文字部件。 */ (node) => node.part),
    ),
  ].sort(
    /* 页眉在正文前，页脚在正文后。 */ (left, right) =>
      orderPart(left) - orderPart(right),
  );
  useEffect(
    /* 从右侧定位映射时，只滚动文档画布。 */ () => {
      const element = root.current?.querySelector<HTMLElement>(
        `[data-template-node="${props.selected[0]}"]`,
      );
      if (element && root.current) {
        const item = element.getBoundingClientRect(),
          canvas = root.current.getBoundingClientRect();
        if (item.top < canvas.top || item.bottom > canvas.bottom)
          root.current.scrollTo({
            top: root.current.scrollTop + item.top - canvas.top - 80,
            behavior: "smooth",
          });
      }
    },
    [props.selected],
  );
  /** 递归呈现表格行、单元格内文字、图片与普通段落。 */
  function renderNode(node: TemplateNode, index: number) {
    const children = tree.get(node.id) ?? [];
    const mapping = mappings.get(node.id)!;
    const active = props.selected.includes(node.id);
    const dim =
      props.filter === "unresolved" &&
      mapping.kind !== "unresolved" &&
      !children.length;
    const label =
      node.kind === "tbl"
        ? "表格"
        : node.kind === "tr"
          ? `第 ${index + 1} 行`
          : node.text ||
            (node.kind === "image"
              ? "图片"
              : children.length
                ? "文本框 / 图片容器"
                : "空白段落");
    const handle = (
      <button
        type="button"
        className={`template-node tone-${mapping.kind} ${active ? "selected" : ""} ${dim ? "dimmed" : ""}`}
        data-template-node={node.id}
        aria-pressed={active}
        aria-label={`选择${label.slice(0, 70)}`}
        onClick={
          /* 点击选中，Shift 点击扩展同级范围。 */ (event) =>
            props.onSelect(node.id, event.shiftKey)
        }
      >
        <span className="template-node-text">
          {node.kind === "image" ? (
            <TemplateImage taskId={props.taskId} nodeId={node.id} />
          ) : node.kind === "p" && node.text ? (
            highlightedText(node.text, mapping.bindings).map(
              /* 精确高亮字段引文，同时保留未替换标签。 */ (chunk, at) =>
                chunk.target ? (
                  <mark key={at} title={targetLabel(chunk.target)}>
                    {chunk.text}
                  </mark>
                ) : (
                  <span key={at}>{chunk.text}</span>
                ),
            )
          ) : (
            label
          )}
        </span>
        <span className="template-node-tags">
          {mapping.bindings.length ? (
            mapping.bindings.map(
              /* 让原文与资料名称直接对应。 */ (field, at) => (
                <span key={at}>{targetLabel(field.target)}</span>
              ),
            )
          ) : (
            <span>{REGION_LABELS[mapping.kind]}</span>
          )}
        </span>
      </button>
    );
    if (!children.length)
      return (
        <div key={node.id} className="template-leaf">
          {handle}
        </div>
      );
    if (node.kind === "tr") {
      const cells = [
        ...new Set(
          children.map(
            /* 用真实单元格父节点保持列分组。 */ (child) => child.parent,
          ),
        ),
      ];
      return (
        <div key={node.id} className="template-table-row">
          {handle}
          <div
            className="template-table-cells"
            style={{
              gridTemplateColumns: `repeat(${cells.length}, minmax(0, 1fr))`,
            }}
          >
            {cells.map(
              /* 同一单元格可以包含多段文字或文本框。 */ (cell) => (
                <div className="template-table-cell" key={cell}>
                  {children
                    .filter(
                      /* 筛出当前单元格的直接内容。 */ (child) =>
                        child.parent === cell,
                    )
                    .map(renderNode)}
                </div>
              ),
            )}
          </div>
        </div>
      );
    }
    return (
      <section
        key={node.id}
        className={
          node.kind === "tbl" ? "template-table" : "template-container"
        }
      >
        {handle}
        {children.map(renderNode)}
      </section>
    );
  }
  return (
    <div
      className="template-canvas-scroll"
      ref={root}
      aria-label="模板识别结构"
    >
      <div className="template-paper">
        {parts.map(
          /* 分开展示页眉、正文和页脚，不伪造真实分页。 */ (part, index) => (
            <section className="template-part" key={part}>
              <div className="template-part-label">
                {part.includes("header")
                  ? "页眉"
                  : part.includes("footer")
                    ? "页脚"
                    : part.includes("footnotes")
                      ? "脚注"
                      : part.includes("endnotes")
                        ? "尾注"
                        : "正文"}
                <span>{index + 1}</span>
              </div>
              {(tree.get(part) ?? []).map(renderNode)}
            </section>
          ),
        )}
      </div>
    </div>
  );
}

/** 确定结构视图的阅读顺序，真实页面位置由 Word 试填展示。 */
function orderPart(part: string) {
  return part.includes("header") ? 0 : part.includes("footer") ? 2 : 1;
}
