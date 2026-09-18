import { useMemo, useState } from "react";
import type { ResumeDocument } from "../../shared/types";
import type { TemplateNode, TemplatePlan } from "./types";
import { adjustmentChoices } from "./adjustments";
import AdvancedMapping from "./AdvancedMapping";
import TemplateCanvas from "./TemplateCanvas";
import TemplateInspector from "./TemplateInspector";

/** 把常用修正放在 Word 试填旁；完整原文与范围操作按需展开 */
export default function TemplateAdjustments({
  nodes,
  plan,
  document,
  taskId,
  selected,
  rangeAnchor,
  onChange,
  onLocate,
  onSelect,
  onRange,
}: {
  nodes: TemplateNode[];
  plan: TemplatePlan;
  document: ResumeDocument;
  taskId: string;
  selected: string[];
  rangeAnchor: string | null;
  onChange: (plan: TemplatePlan) => void;
  onLocate: (id: string) => void;
  onSelect: (id: string, extend?: boolean) => void;
  onRange: (id: string | null) => void;
}) {
  const [advanced, setAdvanced] = useState(false);
  const [showBlanks, setShowBlanks] = useState(false);
  const groups = useMemo(
    /* 修改用途后同步更新分类 */ () => adjustmentChoices(nodes, plan),
    [nodes, plan],
  );
  const known = groups.some(
    /* 高级选区可能不是常用字段 */ (group) =>
      group.choices.some(
        /* 查找选中位置 */ (choice) => choice.id === selected[0],
      ),
  );
  const inspector = (
    <TemplateInspector
      nodes={nodes}
      plan={plan}
      document={document}
      selected={selected}
      advanced={advanced}
      onChange={onChange}
      onSelect={onLocate}
      onRange={
        /* 保留起点；下一次原文点击决定范围 */ () => onRange(selected[0])
      }
    />
  );
  return (
    <section className="template-adjustments" aria-label="修正识别结果">
      <h3>修正识别结果</h3>
      <p className="subtle">
        填错或漏填时，选择对应内容来修正，再更新左侧试填。
      </p>
      <label>
        要修正的内容
        <select
          value={selected[0] ?? ""}
          onChange={
            /* 选择用途时保持 Word 页面可见 */ (event) =>
              onLocate(event.target.value)
          }
        >
          {!known && (
            <option value={selected[0] ?? ""}>
              {selected.length ? "当前选中的原文" : "选择资料或栏目"}
            </option>
          )}
          {groups.map(
            /* 每个栏目聚合到一组；无需竖排全部段落 */ (group, index) => (
              <optgroup label={group.label} key={index}>
                {group.choices.map(
                  /* 重复用途以原文摘要区分位置 */ (choice) => (
                    <option value={choice.id} key={choice.id}>
                      {choice.label} ·{" "}
                      {nodes
                        .find(
                          /* 获取当前位置的原文 */ (node) =>
                            node.id === choice.id,
                        )
                        ?.text.slice(0, 32) || "图片或空位"}
                    </option>
                  ),
                )}
              </optgroup>
            ),
          )}
        </select>
      </label>
      {!advanced && inspector}
      <details
        className="template-structure-options"
        onToggle={
          /* 仅在用户展开时创建完整原文列表 */ (event) => {
            setAdvanced(event.currentTarget.open);
            if (!event.currentTarget.open) onRange(null);
          }
        }
      >
        <summary>高级：选择原文与栏目范围</summary>
        {advanced && (
          <>
            <p className="subtle">
              找不到要改的内容时，在下方选择模板原文。按住 Shift 可选同级范围。
            </p>
            <label className="template-blank-toggle">
              <input
                type="checkbox"
                checked={showBlanks}
                onChange={
                  /* 空白只在需要补充填写位置时显示 */ (event) =>
                    setShowBlanks(event.target.checked)
                }
              />
              显示空白位置
            </label>
            {rangeAnchor && (
              <div className="template-range-prompt">
                已设置起点，请点击同级终点。
                <button onClick={/* 取消未完成的选区 */ () => onRange(null)}>
                  取消选范围
                </button>
              </div>
            )}
            <div className="template-structure-picker">
              <TemplateCanvas
                nodes={nodes}
                plan={plan}
                taskId={taskId}
                selected={selected}
                onSelect={onSelect}
                filter="all"
                showBlanks={showBlanks}
              />
            </div>
            {inspector}
            <AdvancedMapping
              nodes={nodes}
              plan={plan}
              document={document}
              taskId={taskId}
              edit={onChange}
              onLocate={onLocate}
            />
          </>
        )}
      </details>
    </section>
  );
}
