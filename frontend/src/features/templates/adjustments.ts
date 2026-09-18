import type { TemplateNode, TemplatePlan, TextBinding } from "./types.ts";
import { mappingIndex, targetLabel } from "./visual.ts";

interface ChoiceGroup {
  label: string;
  choices: { id: string; label: string }[];
}

/** 按资料用途合并同段字段且仅列出可修正内容；空白和固定原文留在高级选项 */
export function adjustmentChoices(
  nodes: TemplateNode[],
  plan: TemplatePlan,
): ChoiceGroup[] {
  const available = new Set(
    nodes.map(/* 收集仍然存在的位置 */ (node) => node.id),
  );
  /** 同一段可能同时填写姓名、性别和年龄；合并入口避免重复选项 */
  function fields(fields: TextBinding[]) {
    const grouped = new Map<string, Set<string>>();
    for (const field of fields) {
      if (!available.has(field.node)) continue;
      const labels = grouped.get(field.node) ?? new Set<string>();
      labels.add(targetLabel(field.target));
      grouped.set(field.node, labels);
    }
    return nodes
      .filter(
        /* 编辑字段后仍按原文顺序排列以免选择菜单跳动 */ (node) =>
          grouped.has(node.id),
      )
      .map(
        /* 每个真实位置只出现一次 */ (node) => ({
          id: node.id,
          label: [...grouped.get(node.id)!].join(" / "),
        }),
      );
  }
  const groups: ChoiceGroup[] = [
    { label: "个人资料与标题", choices: fields(plan.fields) },
  ];
  for (const region of plan.repeats)
    groups.push({
      label: region.section === "projects" ? "项目经历" : region.section,
      choices: fields(region.fields),
    });
  groups.push({
    label: "照片",
    choices: plan.photos
      .filter(/* 排除已经失效的图片位置 */ (id) => available.has(id))
      .map(
        /* 同模板多张照片仍分别可选 */ (id, index) => ({
          id,
          label: `简历照片${plan.photos.length > 1 ? ` ${index + 1}` : ""}`,
        }),
      ),
  });
  const mappings = mappingIndex(nodes, plan);
  groups.push({
    label: "待确认内容",
    choices: nodes
      .filter(
        /* 未识别原文仍需保留直接修正入口 */ (node) =>
          mappings.get(node.id)?.kind === "unresolved",
      )
      .map(
        /* 用内容摘要代替内部节点编号 */ (node) => ({
          id: node.id,
          label: node.text.slice(0, 45) || "图片用途待确认",
        }),
      ),
  });
  return groups.filter(
    /* 不展示没有内容的分类 */ (group) => group.choices.length > 0,
  );
}
