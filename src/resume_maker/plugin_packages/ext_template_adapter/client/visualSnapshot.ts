import type { TemplateNode, TemplatePlan } from "./types.ts";
import {
  descendants,
  mappingIndex,
  repeatNodes,
  templateChildren,
} from "./visual.ts";

export type TemplateSnapshot = ReturnType<typeof templateSnapshot>;

/** 为画布、选区、用途菜单建立同一份结构及映射索引 */
export function templateSnapshot(nodes: TemplateNode[], plan: TemplatePlan) {
  const repeatMembers = plan.repeats.map((_, index) =>
    repeatNodes(nodes, plan, index),
  );
  const memberships = new Map<string, number[]>();
  repeatMembers.forEach((members, index) => {
    for (const id of members) {
      const regions = memberships.get(id) ?? [];
      regions.push(index);
      memberships.set(id, regions);
    }
  });
  return {
    nodes,
    plan,
    byId: new Map(nodes.map((node) => [node.id, node])),
    children: templateChildren(nodes),
    mappings: mappingIndex(nodes, plan, repeatMembers),
    memberships,
    samples: plan.repeats.map(
      (_, index) => new Set(repeatNodes(nodes, plan, index, true)),
    ),
  };
}

/** 按文档顺序展开选区，保留所有相交区域以检查跨栏目操作 */
export function templateSelection(
  snapshot: TemplateSnapshot,
  selected: string[],
) {
  const { nodes, plan, byId, mappings, memberships, samples } = snapshot;
  const node = byId.get(selected[0]);
  if (!node) return null;
  const ids = new Set(descendants(nodes, selected));
  const info = mappings.get(node.id)!;
  const region = plan.repeats[info.region];
  const touched = plan.repeats.map(() => false);
  for (const id of ids)
    for (const index of memberships.get(id) ?? []) touched[index] = true;
  const hasRepeat = touched.some(Boolean);
  const inSample =
    !hasRepeat ||
    (!!region && [...ids].every((id) => samples[info.region].has(id)));
  return {
    node,
    ids,
    info,
    region,
    touched,
    hasRepeat,
    inSample,
    available: [...ids]
      .map((id) => byId.get(id)!)
      .filter((item) => item.kind === "p" && (item.text || item.can_insert)),
    fields: (region ? region.fields : plan.fields).filter((field) =>
      ids.has(field.node),
    ),
    canRange: selected.every((id) => byId.get(id)?.kind !== "image"),
  };
}
