import { useState } from "react";
import { Crosshair, ListTree, Plus, Trash2 } from "lucide-react";
import type { ResumeDocument } from "../../shared/types";
import type { TemplateNode, TemplatePlan, TextBinding } from "./types";
import {
  ENTRY_LABELS,
  newBinding,
  nodeLabel,
  personalTargets,
} from "./mapping";
import {
  clearNodes,
  descendants,
  nodeMapping,
  REGION_LABELS,
  repeatNodes,
} from "./visual";
import BindingEditor from "./BindingEditor";

interface Props {
  nodes: TemplateNode[];
  plan: TemplatePlan;
  document: ResumeDocument;
  selected: string[];
  onChange: (plan: TemplatePlan) => void;
  onSelect: (id: string) => void;
  onRange: () => void;
}

/** 编辑画布当前选区的字段、照片用途和重复范围，所有修改仍需完整校验。 */
export default function TemplateInspector({
  nodes,
  plan,
  document,
  selected,
  onChange,
  onSelect,
  onRange,
}: Props) {
  const [warning, setWarning] = useState("");
  const [section, setSection] = useState("projects");
  const [targetRegion, setTargetRegion] = useState(0);
  const node = nodes.find(
    /* 定位选区的第一个节点。 */ (item) => item.id === selected[0],
  );
  if (!node)
    return (
      <div className="template-selection-empty">
        <Crosshair size={28} />
        <h3>选择模板中的内容</h3>
        <p>点击左侧文字、图片或表格行，在这里核对并调整映射。</p>
        <p className="subtle">按住 Shift 选择同级范围，也可先设置范围起点。</p>
      </div>
    );
  const ids = new Set(descendants(nodes, selected));
  const info = nodeMapping(nodes, plan, node);
  const region = plan.repeats[info.region];
  const touched = plan.repeats.map(
    /* 判断选区是否同时跨越多个栏目。 */ (_, index) =>
      repeatNodes(nodes, plan, index).some(
        /* 检测选区中的任意位置。 */ (id) => ids.has(id),
      ),
  );
  const hasRepeat = touched.some(Boolean);
  const sampleIds = new Set(repeatNodes(nodes, plan, info.region, true));
  const inSample =
    !hasRepeat ||
    (!!region &&
      [...ids].every(
        /* 所有选中内容必须属于同一个单条样本。 */ (id) => sampleIds.has(id),
      ));
  const selectedRegion = region
    ? info.region
    : Math.min(targetRegion, plan.repeats.length - 1);
  const available = nodes.filter(
    /* 只在选区内提供能映射的文字位置。 */ (item) =>
      ids.has(item.id) && item.kind === "p" && (item.text || item.can_insert),
  );
  const fields = (region ? region.fields : plan.fields).filter(
    /* 所选容器内的字段一起调整。 */ (field) => ids.has(field.node),
  );
  const canRange = selected.every(
    /* 图片不能作为重复区边界。 */ (id) =>
      nodes.find(/* 定位选中的节点。 */ (item) => item.id === id)?.kind !==
      "image",
  );
  /** 更新选区的字段集合，保留所有其他位置的映射。 */
  function updateFields(value: TextBinding[]) {
    if (
      region &&
      !value.length &&
      !region.fields.some(
        /* 当前选区外必须仍有可重复填写的字段。 */ (field) =>
          !ids.has(field.node),
      )
    ) {
      setWarning(
        "重复栏目至少需要一个字段。若要全部保留，请先取消这个栏目映射。",
      );
      return;
    }
    setWarning("");
    const cleared = clearNodes(plan, nodes, selected);
    if (region) {
      onChange({
        ...cleared,
        repeats: plan.repeats.map(
          /* 只替换当前样本内的字段。 */ (item, index) =>
            index === info.region
              ? {
                  ...item,
                  fields: [
                    ...item.fields.filter(
                      /* 保留样本中其他位置。 */ (field) =>
                        !ids.has(field.node),
                    ),
                    ...value,
                  ],
                }
              : item,
        ),
      });
    } else onChange({ ...cleared, fields: [...cleared.fields, ...value] });
  }
  /** 把选区明确分类，固定文字只能逐段确认，避免整个表格掩盖遗漏信息。 */
  function classify(kind: "photos" | "keep" | "remove") {
    if (
      region &&
      !region.fields.some(
        /* 固定内容不能清空整个重复栏目。 */ (field) => !ids.has(field.node),
      )
    ) {
      setWarning(
        "重复栏目至少需要一个字段。若要全部保留，请先取消这个栏目映射。",
      );
      return;
    }
    setWarning("");
    const cleared = clearNodes(plan, nodes, selected);
    const chosen =
      kind === "keep"
        ? nodes
            .filter(
              /* 固定内容逐段或逐图记录。 */ (item) =>
                ids.has(item.id) &&
                (item.kind === "image" || (item.kind === "p" && !!item.text)),
            )
            .map(/* 保留稳定位置。 */ (item) => item.id)
        : selected;
    onChange({
      ...cleared,
      [kind]: [...new Set([...cleared[kind], ...chosen])],
      repeats: region
        ? cleared.repeats.map(
            /* 固定标签不能继续保留同位置的字段映射。 */ (item, index) =>
              index === info.region
                ? {
                    ...item,
                    fields: item.fields.filter(
                      /* 仅撤回所选标签的字段。 */ (field) =>
                        !ids.has(field.node),
                    ),
                  }
                : item,
          )
        : cleared.repeats,
    });
  }
  /** 以选区作为一条完整样例建立重复栏目，再按需要扩展全部示例范围。 */
  function addRegion() {
    if (!available.length) return;
    const cleared = clearNodes(plan, nodes, selected);
    onChange({
      ...cleared,
      repeats: [
        ...cleared.repeats,
        {
          section,
          start: selected[0],
          end: selected[selected.length - 1],
          sample_start: selected[0],
          sample_end: selected[selected.length - 1],
          fields: [newBinding(available[0], "title")],
        },
      ],
    });
  }
  /** 把当前同级选区写入指定栏目的重复范围或单条样本，随后由后端核验边界。 */
  function setRange(sample: boolean) {
    const index = selectedRegion;
    onChange({
      ...plan,
      repeats: plan.repeats.map(
        /* 仅更新用户指定的栏目范围。 */ (item, at) =>
          at === index
            ? {
                ...item,
                ...(sample
                  ? {
                      sample_start: selected[0],
                      sample_end: selected[selected.length - 1],
                    }
                  : { start: selected[0], end: selected[selected.length - 1] }),
              }
            : item,
      ),
    });
  }
  return (
    <div className="template-selection">
      {warning && (
        <p className="template-notice" role="status">
          {warning}
        </p>
      )}
      <div className="section-heading">
        <h3>所选区域</h3>
        <span className={`template-status tone-${info.kind}`}>
          {REGION_LABELS[info.kind]}
        </span>
      </div>
      <p className="template-selection-source">
        {selected.length > 1
          ? `已选 ${selected.length} 个同级区域`
          : nodeLabel(node)}
      </p>
      {canRange && (
        <button onClick={onRange}>
          <Crosshair size={14} />
          从此处开始选范围
        </button>
      )}
      {region && (
        <div className="template-repeat-context">
          <ListTree size={16} />
          <span>
            属于 {region.section === "projects" ? "项目经历" : region.section}
            {inSample ? " · 单条样本" : " · 原有示例"}
          </span>
        </div>
      )}
      {!inSample ? (
        <div className="template-notice">
          <p>
            选区包含原有示例或跨越栏目边界。请缩小选区，字段映射应在同一条样本中调整。
          </p>
          <button
            onClick={
              /* 定位真正作为样式来源的条目。 */ () =>
                onSelect(plan.repeats[touched.findIndex(Boolean)].sample_start)
            }
          >
            定位单条样本
          </button>
        </div>
      ) : (
        <>
          {available.length > 0 && (
            <>
              <h4>{region ? "条目字段" : "资料字段"}</h4>
              {region && (
                <p className="subtle">
                  每个重复栏目至少保留一个字段；全部设为固定内容时，请取消该栏目映射。
                </p>
              )}
              <BindingEditor
                fields={fields}
                nodes={available}
                targets={region ? ENTRY_LABELS : personalTargets(document)}
                onChange={updateFields}
                onLocate={onSelect}
              />
            </>
          )}
          <div className="template-selection-actions">
            {node.kind === "image" && !region && (
              <button
                onClick={
                  /* 使用当前个人照片替换所选图片。 */ () => classify("photos")
                }
              >
                设为简历照片
              </button>
            )}
            <button
              onClick={
                /* 明确保留固定标签或装饰内容。 */ () => classify("keep")
              }
            >
              保留为固定内容
            </button>
            {!region && (
              <button
                onClick={
                  /* 删除整段旧示例或所选图片。 */ () => classify("remove")
                }
              >
                <Trash2 size={14} />
                删除原文
              </button>
            )}
            {!region && (
              <button
                onClick={
                  /* 撤回所选位置的全部分类，重新核对用途。 */ () =>
                    onChange(clearNodes(plan, nodes, selected))
                }
              >
                清除映射
              </button>
            )}
          </div>
        </>
      )}
      {canRange && (
        <details
          className="template-range-editor"
          open={selected.length > 1 || !!region}
        >
          <summary>重复栏目与范围</summary>
          <p className="subtle">
            先选一条完整样例，再选择全部旧条目作为替换范围。教育表格可直接选中整行。
          </p>
          {!hasRepeat && (
            <>
              <label>
                新建区域对应栏目
                <select
                  value={section}
                  onChange={
                    /* 选择新区域要填写的栏目。 */ (event) =>
                      setSection(event.target.value)
                  }
                >
                  <option value="projects">项目经历</option>
                  {document.sections
                    .filter(
                      /* 项目区已单独列出。 */ (item) =>
                        item.kind !== "projects",
                    )
                    .map(
                      /* 使用当前资料中的栏目名称。 */ (item) => (
                        <option key={item.id} value={item.title}>
                          {item.title}
                        </option>
                      ),
                    )}
                </select>
              </label>
              <button disabled={!available.length} onClick={addRegion}>
                <Plus size={14} />
                设为新的重复栏目
              </button>
            </>
          )}
          {plan.repeats.length > 0 && (
            <>
              {!region && (
                <label>
                  调整已有栏目
                  <select
                    value={selectedRegion}
                    onChange={
                      /* 将选区用于明确指定的栏目。 */ (event) =>
                        setTargetRegion(Number(event.target.value))
                    }
                  >
                    {plan.repeats.map(
                      /* 区域同名时通过顺序区别。 */ (item, index) => (
                        <option value={index} key={index}>
                          {index + 1}.{" "}
                          {item.section === "projects"
                            ? "项目经历"
                            : item.section}
                        </option>
                      ),
                    )}
                  </select>
                </label>
              )}
              <div className="template-selection-actions">
                <button
                  onClick={
                    /* 使用当前所选起止节点作为全部示例范围。 */ () =>
                      setRange(false)
                  }
                >
                  设为全部示例范围
                </button>
                <button
                  onClick={
                    /* 使用当前所选起止节点作为单条样本。 */ () =>
                      setRange(true)
                  }
                >
                  设为单条样本
                </button>
              </div>
            </>
          )}
          {region && (
            <button
              onClick={
                /* 取消栏目配置，原文重新进入待处理清单。 */ () =>
                  onChange({
                    ...plan,
                    repeats: plan.repeats.filter(
                      /* 保留其他重复栏目。 */ (_, index) =>
                        index !== info.region,
                    ),
                  })
              }
            >
              取消这个栏目映射
            </button>
          )}
        </details>
      )}
    </div>
  );
}
