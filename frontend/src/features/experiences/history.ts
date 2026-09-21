import type {
  Branch,
  Revision,
  UncommittedRevision,
} from "../../shared/types/index";
import { projectBodyOrder } from "./bodyOrder.ts";

export type HistoryRevision = Revision & { uncommitted?: boolean };

export const HISTORY_ROW_HEIGHT = 76;
export const BRANCH_COLORS = [
  "#55a884",
  "#9b86d8",
  "#549dc7",
  "#cd9963",
  "#cf7fa0",
  "#6aa8a1",
];

/** 根据父修订关系计算历史图坐标 */
export function historyGraph(
  revisions: Revision[],
  branches: Branch[],
  working: UncommittedRevision[] = [],
) {
  const saved = [...revisions].sort(
    /* 新版本排在上方，序号在项目内唯一 */ (a, b) => b.number - a.number,
  );
  const ordered: HistoryRevision[] = saved.flatMap(
    /* 草稿放在基线版本旁边并独立编号 */ (base) => {
      const draft = working.find(
        /* 将每份未提交工作副本连接到准确的基线 */ (item) =>
          item.base_revision === base.id,
      );
      if (!draft) return [base];
      return [
        {
          ...base,
          id: `working:${base.id}`,
          parent_id: base.id,
          content: draft.content,
          created_at: draft.updated_at,
          origin: "working",
          uncommitted: true,
        },
        base,
      ];
    },
  );
  const nodes = ordered.map(
    /* 同一分支使用固定泳道和颜色 */ (revision, index) => {
      const lane = Math.max(
        0,
        branches.findIndex(
          /* 找到修订所属分支 */ (branch) => branch.id === revision.branch_id,
        ),
      );
      return {
        revision,
        x: 18 + lane * 24,
        y: index * HISTORY_ROW_HEIGHT + HISTORY_ROW_HEIGHT / 2,
        color: BRANCH_COLORS[lane % BRANCH_COLORS.length],
      };
    },
  );
  const byId = new Map(
    nodes.map(
      /* 以标识查找父节点，支持历史存在分叉 */ (node) => [
        node.revision.id,
        node,
      ],
    ),
  );
  const edges = nodes.flatMap(
    /* 仅绘制数据库实际记录的父子边 */ (node) => {
      const parent = byId.get(node.revision.parent_id ?? "");
      if (!parent) return [];
      const path =
        node.x === parent.x
          ? `M ${node.x} ${node.y} V ${parent.y}`
          : `M ${node.x} ${node.y} V ${parent.y - 28} Q ${node.x} ${parent.y - 8} ${parent.x} ${parent.y}`;
      return [
        {
          from: node.revision.id,
          to: parent.revision.id,
          path,
          color: node.color,
          uncommitted: !!node.revision.uncommitted,
        },
      ];
    },
  );
  return {
    nodes,
    edges,
    width: Math.max(44, branches.length * 24 + 14),
    height: nodes.length * HISTORY_ROW_HEIGHT,
  };
}

/** 将存储来源映射为用户可理解的历史动作 */
export function revisionOrigin(origin: string) {
  return (
    (
      {
        ai: "AI 建议保存",
        restore: "历史恢复",
        branch: "创建分支",
        manual: "人工保存",
      } as Record<string, string>
    )[origin] ?? "保存版本"
  );
}

/** 概括相对于父版本的内容变更，分支起点允许只有关系变化 */
export function revisionChanges(revision: Revision, parent?: Revision) {
  if (!parent) return ["初始经历"];
  const labels = {
    title: "项目标题",
    period: "参与时间",
    role: "担任角色",
    stack: "技术栈",
    description: "项目描述",
  } as const;
  const changes: string[] = [];
  if (
    JSON.stringify(
      revision.content.body_order == null
        ? null
        : projectBodyOrder(revision.content, {}),
    ) !==
    JSON.stringify(
      parent.content.body_order == null
        ? null
        : projectBodyOrder(parent.content, {}),
    )
  )
    changes.push("基本信息顺序");
  for (const key of Object.keys(labels) as (keyof typeof labels)[]) {
    if (
      JSON.stringify(revision.content[key]) !==
      JSON.stringify(parent.content[key])
    )
      changes.push(labels[key]);
  }
  if (
    JSON.stringify([...(revision.content.hidden_fields ?? [])].sort()) !==
    JSON.stringify([...(parent.content.hidden_fields ?? [])].sort())
  )
    changes.push("信息显隐");
  if (
    JSON.stringify(revision.content.custom_fields ?? []) !==
    JSON.stringify(parent.content.custom_fields ?? [])
  )
    changes.push("自定义信息");
  const before = new Map(
    parent.content.highlights.map(
      /* 按稳定亮点标识比较 */ (point) => [point.id, point],
    ),
  );
  let added = 0,
    edited = 0;
  for (const point of revision.content.highlights) {
    const old = before.get(point.id);
    if (!old) added++;
    else if (JSON.stringify(old) !== JSON.stringify(point)) edited++;
    before.delete(point.id);
  }
  if (added) changes.push(`新增 ${added} 条亮点`);
  if (edited) changes.push(`修改 ${edited} 条亮点`);
  if (before.size) changes.push(`删除 ${before.size} 条亮点`);
  if (
    !added &&
    !before.size &&
    JSON.stringify(
      revision.content.highlights.map(/* 比较排列顺序 */ (point) => point.id),
    ) !==
      JSON.stringify(
        parent.content.highlights.map(/* 提取父版本顺序 */ (point) => point.id),
      )
  )
    changes.push("亮点顺序");
  return changes.length ? changes : ["经历内容未变"];
}
