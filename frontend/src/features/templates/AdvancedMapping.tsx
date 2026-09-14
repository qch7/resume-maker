import { useState } from "react";
import type { ResumeDocument } from "../../shared/types";
import type { TemplateNode, TemplatePlan, RepeatBinding } from "./types";
import BindingEditor from "./BindingEditor";
import TemplateImage from "./TemplateImage";
import {
  ENTRY_LABELS,
  newBinding,
  nodeLabel,
  personalTargets,
} from "./mapping";

/** 提供完整映射清单与精确边界编辑，补充画布中的选区操作。 */
export default function AdvancedMapping({
  nodes,
  plan,
  document,
  taskId,
  edit,
  onLocate,
}: {
  nodes: TemplateNode[];
  plan: TemplatePlan;
  document: ResumeDocument;
  taskId: string;
  edit: (plan: TemplatePlan) => void;
  onLocate: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  /** 调整指定重复区域，保留其他字段和区域的配置。 */
  function changeRegion(index: number, region: RepeatBinding) {
    edit({
      ...plan,
      repeats: plan.repeats.map(
        /* 仅替换当前区域。 */ (item, at) => (at === index ? region : item),
      ),
    });
  }
  return (
    <details
      className="template-advanced"
      onToggle={
        /* 仅在展开时创建完整字段清单，避免大模板生成大量隐藏选项。 */ (
          event,
        ) => setExpanded(event.currentTarget.open)
      }
    >
      <summary>全部映射与高级调整</summary>
      {expanded && (
        <div>
          <h4>基本信息与栏目标题</h4>
          <BindingEditor
            onLocate={onLocate}
            fields={plan.fields}
            nodes={nodes}
            targets={personalTargets(document)}
            onChange={
              /* 更新全局字段映射。 */ (fields) => edit({ ...plan, fields })
            }
          />
          <h4>
            重复栏目 <span className="subtle">按当前资料自动增减条目</span>
          </h4>
          {plan.repeats.map(
            /* 每个栏目独立核对重复样式。 */ (region, index) => (
              <details className="template-region" key={index}>
                <summary>
                  {region.section === "projects" ? "项目经历" : region.section}{" "}
                  · {region.fields.length} 个字段
                </summary>
                <label>
                  对应栏目
                  <select
                    value={region.section}
                    onChange={
                      /* 选择此区域接收的资料栏目。 */ (event) =>
                        changeRegion(index, {
                          ...region,
                          section: event.target.value,
                        })
                    }
                  >
                    <option value="projects">项目经历（固定版本）</option>
                    {document.sections
                      .filter(
                        /* 项目区使用固定选项。 */ (section) =>
                          section.kind !== "projects",
                      )
                      .map(
                        /* 其他栏目按当前名称匹配。 */ (section) => (
                          <option value={section.title} key={section.id}>
                            {section.title}
                          </option>
                        ),
                      )}
                    {!document.sections.some(
                      /* 保留不匹配的识别结果供用户纠正。 */ (section) =>
                        section.title === region.section,
                    ) &&
                      region.section !== "projects" && (
                        <option value={region.section}>
                          {region.section} · 请核对
                        </option>
                      )}
                  </select>
                </label>
                <BindingEditor
                  onLocate={onLocate}
                  fields={region.fields}
                  nodes={nodes}
                  targets={ENTRY_LABELS}
                  onChange={
                    /* 更新样本内的字段。 */ (fields) =>
                      changeRegion(index, { ...region, fields })
                  }
                />
                <details>
                  <summary>调整重复范围与样式样本</summary>
                  <div className="template-region-range">
                    {(
                      [
                        ["start", "全部示例起点"],
                        ["end", "全部示例终点"],
                        ["sample_start", "单条样本起点"],
                        ["sample_end", "单条样本终点"],
                      ] as const
                    ).map(
                      /* 起止范围均为包含当前位置。 */ ([key, label]) => (
                        <label key={key}>
                          {label}
                          <select
                            value={region[key]}
                            onChange={
                              /* 校验前允许用户调整结构边界。 */ (event) =>
                                changeRegion(index, {
                                  ...region,
                                  [key]: event.target.value,
                                })
                            }
                          >
                            {nodes
                              .filter(
                                /* 重复范围可以是段落、表格或整行。 */ (node) =>
                                  node.kind !== "image",
                              )
                              .map(
                                /* 展示原文摘要作为位置依据。 */ (node) => (
                                  <option value={node.id} key={node.id}>
                                    {nodeLabel(node)}
                                  </option>
                                ),
                              )}
                          </select>
                        </label>
                      ),
                    )}
                  </div>
                </details>
                <button
                  onClick={
                    /* 删除区域配置，原文会重新进入待处理清单。 */ () =>
                      edit({
                        ...plan,
                        repeats: plan.repeats.filter(
                          /* 保留其他区域。 */ (_, at) => at !== index,
                        ),
                      })
                  }
                >
                  移除此重复栏目
                </button>
              </details>
            ),
          )}
          <button
            onClick={
              /* 以一个可见段落创建待调整的栏目区域。 */ () => {
                const node = nodes.find(
                  /* 选择可编辑的非空段落。 */ (item) =>
                    item.kind === "p" && item.text,
                );
                if (node)
                  edit({
                    ...plan,
                    repeats: [
                      ...plan.repeats,
                      {
                        section: "projects",
                        start: node.id,
                        end: node.id,
                        sample_start: node.id,
                        sample_end: node.id,
                        fields: [newBinding(node, "title")],
                      },
                    ],
                  });
              }
            }
          >
            添加重复栏目
          </button>
          <details>
            <summary>
              照片、固定内容与删除项（
              {plan.photos.length + plan.keep.length + plan.remove.length}）
            </summary>
            {(
              [
                ["photos", "替换照片"],
                ["keep", "保留固定内容"],
                ["remove", "删除示例内容"],
              ] as const
            ).map(
              /* 所有原文处置都可撤销并重新核对。 */ ([key, label]) => (
                <div key={key}>
                  <strong>{label}</strong>
                  {plan[key].map(
                    /* 展示每个明确处理的节点。 */ (id) => (
                      <div className="template-unresolved" key={id}>
                        {nodes.some(
                          /* 显示照片和装饰图片的真实内容。 */ (node) =>
                            node.id === id && node.kind === "image",
                        ) && <TemplateImage taskId={taskId} nodeId={id} />}
                        <span>
                          {nodes
                            .find(/* 读取原文摘要。 */ (node) => node.id === id)
                            ?.text.slice(0, 150) || id}
                        </span>
                        <button
                          onClick={
                            /* 撤回当前分类。 */ () =>
                              edit({
                                ...plan,
                                [key]: plan[key].filter(
                                  /* 仅移除所选节点。 */ (value) =>
                                    value !== id,
                                ),
                              })
                          }
                        >
                          重新分类
                        </button>
                      </div>
                    ),
                  )}
                </div>
              ),
            )}
          </details>
        </div>
      )}
    </details>
  );
}
