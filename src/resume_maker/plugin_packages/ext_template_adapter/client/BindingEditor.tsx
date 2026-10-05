import { Plus, Trash2 } from "lucide-react";
import { newBinding, nodeLabel } from "./mapping";
import type { TemplateNode, TextBinding } from "./types";

/** 核对原文和目标资料并在详情中调整位置 */
export default function BindingEditor({
  fields,
  nodes,
  targets,
  onChange,
  onLocate,
  advanced = true,
}: {
  fields: TextBinding[];
  nodes: TemplateNode[];
  targets: Record<string, string>;
  onChange: (fields: TextBinding[]) => void;
  onLocate?: (nodeId: string) => void;
  advanced?: boolean;
}) {
  const paragraphs = nodes.filter(
    /* 只允许在没有照片等对象的空段落中补字段 */ (node) =>
      node.kind === "p" && (node.text || node.can_insert),
  );
  /** 原位更新一条映射，保持其余字段的引文和顺序 */
  function update(index: number, value: TextBinding) {
    onChange(
      fields.map(
        /* 只修改选定映射 */ (field, at) => (at === index ? value : field),
      ),
    );
  }
  return (
    <div className="template-bindings">
      {fields.map(
        /* 每条映射独立核对原文和资料含义 */ (field, index) => (
          <div className="template-binding" key={index}>
            <label>
              模板原文
              <input
                value={field.quote}
                placeholder="空引文仅用于原本空白的段落"
                onChange={
                  /* 编辑精确引文 */ (event) =>
                    update(index, { ...field, quote: event.target.value })
                }
              />
            </label>
            <label>
              替换为
              <select
                value={field.target}
                onChange={
                  /* 选择资料字段 */ (event) =>
                    update(index, { ...field, target: event.target.value })
                }
              >
                {!targets[field.target] && (
                  <option value={field.target}>
                    {field.target} · 请重新选择
                  </option>
                )}
                {Object.entries(targets).map(
                  /* 展示可替换资料名称 */ ([target, label]) => (
                    <option key={target} value={target}>
                      {label}
                    </option>
                  ),
                )}
              </select>
            </label>
            <button
              className="icon-button"
              aria-label="移除字段映射"
              onClick={
                /* 移除映射后原文需重新分类 */ () =>
                  onChange(
                    fields.filter(/* 保留其余映射 */ (_, at) => at !== index),
                  )
              }
            >
              <Trash2 size={15} />
            </button>
            {advanced && (
              <details>
                <summary>调整位置</summary>
                {onLocate && (
                  <button
                    onClick={
                      /* 从字段表单定位回可视化区域 */ () =>
                        onLocate(field.node)
                    }
                  >
                    在模板中定位
                  </button>
                )}
                <label>
                  所在段落
                  <select
                    value={field.node}
                    onChange={
                      /* 调整节点并使用该段原文 */ (event) => {
                        const node = paragraphs.find(
                          /* 定位选中段落 */ (item) =>
                            item.id === event.target.value,
                        )!;
                        update(index, {
                          ...field,
                          node: node.id,
                          quote: node.text,
                        });
                      }
                    }
                  >
                    {paragraphs.map(
                      /* 以位置和摘要列出段落 */ (node) => (
                        <option key={node.id} value={node.id}>
                          {nodeLabel(node)}
                        </option>
                      ),
                    )}
                  </select>
                </label>
                <label>
                  同段第几处
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={field.occurrence}
                    onChange={
                      /* 选择重复文字中的具体出现位置 */ (event) =>
                        update(index, {
                          ...field,
                          occurrence: Number(event.target.value),
                        })
                    }
                  />
                </label>
              </details>
            )}
          </div>
        ),
      )}
      {advanced && (
        <button
          disabled={!paragraphs.length}
          onClick={
            /* 添加一条待核对映射 */ () =>
              onChange([
                ...fields,
                newBinding(paragraphs[0], Object.keys(targets)[0]),
              ])
          }
        >
          <Plus size={15} />
          添加字段映射
        </button>
      )}
    </div>
  );
}
