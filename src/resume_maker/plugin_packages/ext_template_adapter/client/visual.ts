import type { TemplateNode, TemplatePlan, TextBinding } from "./types.ts";
import { ENTRY_LABELS, PERSONAL_LABELS } from "./mapping.ts";

export type RegionKind =
  | "field"
  | "repeat"
  | "photo"
  | "keep"
  | "remove"
  | "unresolved"
  | "blank"
  | "container";
export const REGION_LABELS: Record<RegionKind, string> = {
  field: "资料字段",
  repeat: "重复栏目",
  photo: "照片",
  keep: "固定内容",
  remove: "删除示例",
  unresolved: "待处理",
  blank: "空白位置",
  container: "结构容器",
};

/** 仅允许同一容器内同级节点组成闭区间 */
export function siblingRange(
  nodes: TemplateNode[],
  start: string,
  end: string,
) {
  const first = nodes.find(/* 定位范围起点 */ (node) => node.id === start);
  const last = nodes.find(/* 定位范围终点 */ (node) => node.id === end);
  if (
    !first ||
    !last ||
    first.kind === "image" ||
    last.kind === "image" ||
    first.parent !== last.parent ||
    first.part !== last.part
  )
    return [];
  const siblings = nodes.filter(
    /* 只取同容器的段落、表格或行 */ (node) =>
      node.parent === first.parent && node.part === first.part,
  );
  const left = siblings.indexOf(first),
    right = siblings.indexOf(last);
  return siblings
    .slice(Math.min(left, right), Math.max(left, right) + 1)
    .map(/* 保持文档原顺序 */ (node) => node.id);
}

/** 展开选区包含的内层段落、图片和表格，用于分色及清理重叠分类 */
export function descendants(nodes: TemplateNode[], ids: string[]) {
  const selected = new Set(ids);
  return nodes
    .filter(
      /* 祖先在选区内的节点也属于操作范围 */ (node) =>
        selected.has(node.id) ||
        node.ancestors.some(/* 查找被选择的容器 */ (id) => selected.has(id)),
    )
    .map(/* 返回稳定节点标识 */ (node) => node.id);
}

/** 生成完整重复区或单条样本的节点清单，边界调整立即反映在画布 */
export function repeatNodes(
  nodes: TemplateNode[],
  plan: TemplatePlan,
  index: number,
  sample = false,
) {
  const region = plan.repeats[index];
  if (!region) return [];
  return descendants(
    nodes,
    siblingRange(
      nodes,
      sample ? region.sample_start : region.start,
      sample ? region.sample_end : region.end,
    ),
  );
}

/** 预先建立节点用途索引以避免画布逐节点扫描重复区 */
export function mappingIndex(nodes: TemplateNode[], plan: TemplatePlan) {
  const regions = new Map<string, number>();
  plan.repeats.forEach(
    /* 按方案顺序标记区域归属，重叠仍由校验报告 */ (_, index) => {
      for (const id of repeatNodes(nodes, plan, index))
        if (!regions.has(id)) regions.set(id, index);
    },
  );
  const fields = new Map<string, TextBinding[]>();
  for (const field of [
    ...plan.fields,
    ...plan.repeats.flatMap(/* 合并样本内字段 */ (region) => region.fields),
  ]) {
    fields.set(field.node, [...(fields.get(field.node) ?? []), field]);
  }
  const removed = new Set(descendants(nodes, plan.remove));
  const kept = new Set(plan.keep),
    photos = new Set(plan.photos);
  return new Map(
    nodes.map(
      /* 为每个结构位置计算用途和精确字段 */ (node) => {
        const region = regions.get(node.id) ?? -1;
        const bindings = fields.get(node.id) ?? [];
        let kind: RegionKind =
          node.text || node.kind === "image" ? "unresolved" : "blank";
        if (
          node.kind === "tbl" ||
          node.kind === "tr" ||
          (node.kind === "p" && !node.text && !node.can_insert)
        )
          kind = "container";
        if (kept.has(node.id)) kind = "keep";
        if (region >= 0) kind = "repeat";
        if (bindings.length) kind = "field";
        if (photos.has(node.id)) kind = "photo";
        if (removed.has(node.id)) kind = "remove";
        return [node.id, { kind, region, bindings }];
      },
    ),
  );
}

/** 给单个选区读取和画布一致的用途 */
export function nodeMapping(
  nodes: TemplateNode[],
  plan: TemplatePlan,
  node: TemplateNode,
) {
  return mappingIndex(nodes, plan).get(node.id)!;
}

/** 将字段标识转为显示名称 */
export function targetLabel(target: string) {
  if (target.startsWith("personal.custom:"))
    return target.slice("personal.custom:".length);
  if (target.startsWith("section-title:"))
    return `栏目标题 · ${target.slice("section-title:".length)}`;
  const separator = target.lastIndexOf(" · ");
  const entry = target.slice(separator + 3);
  if (separator >= 0 && ENTRY_LABELS[entry])
    return `${target.slice(0, separator)} · ${entry === "title" ? "名称" : ENTRY_LABELS[entry]}`;
  return PERSONAL_LABELS[target] ?? ENTRY_LABELS[target] ?? target;
}

/** 按引文及出现次数拆分原文并保留字段之间的标签和标点 */
export function highlightedText(text: string, fields: TextBinding[]) {
  const ranges = fields
    .flatMap(
      /* 引文不匹配时保留原文，交给后端报告校验错误 */ (field) => {
        if (!field.quote) return [];
        let start = -1;
        for (let index = 0; index < field.occurrence; index++) {
          start = text.indexOf(field.quote, start + 1);
          if (start < 0) return [];
        }
        return [
          { start, end: start + field.quote.length, target: field.target },
        ];
      },
    )
    .sort(/* 按原文顺序渲染高亮 */ (left, right) => left.start - right.start);
  const chunks: { text: string; target?: string }[] = [];
  let cursor = 0;
  for (const range of ranges) {
    if (range.start < cursor) continue;
    if (range.start > cursor)
      chunks.push({ text: text.slice(cursor, range.start) });
    chunks.push({
      text: text.slice(range.start, range.end),
      target: range.target,
    });
    cursor = range.end;
  }
  if (cursor < text.length) chunks.push({ text: text.slice(cursor) });
  return chunks;
}

/** 移除选中位置的独立映射和处置 */
export function clearNodes(
  plan: TemplatePlan,
  nodes: TemplateNode[],
  selected: string[],
): TemplatePlan {
  const ids = new Set(descendants(nodes, selected));
  const ancestors = new Set(
    nodes
      .filter(/* 收集选中位置的祖先 */ (node) => ids.has(node.id))
      .flatMap(/* 清除覆盖该位置的整体删除标记 */ (node) => node.ancestors),
  );
  return {
    ...plan,
    fields: plan.fields.filter(
      /* 清理该位置原有资料字段 */ (field) => !ids.has(field.node),
    ),
    photos: plan.photos.filter(/* 保留选区外的照片 */ (id) => !ids.has(id)),
    keep: plan.keep.filter(/* 保留选区外的固定文字 */ (id) => !ids.has(id)),
    remove: plan.remove.filter(
      /* 不再用整体删除覆盖新映射 */ (id) => !ids.has(id) && !ancestors.has(id),
    ),
  };
}
