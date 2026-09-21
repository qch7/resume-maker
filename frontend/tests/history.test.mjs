import { test } from "node:test";
import assert from "node:assert/strict";
import {
  historyGraph,
  revisionChanges,
} from "../src/features/experiences/history.ts";

test("uncommitted nodes belong to their own baseline and never consume revision numbers", /* 多个分支的草稿分别连接到对应的历史节点 */ () => {
  const revisions = [
    {
      id: "r1",
      number: 1,
      parent_id: null,
      branch_id: "main",
      content: { title: "Initial" },
    },
    {
      id: "r2",
      number: 2,
      parent_id: "r1",
      branch_id: "main",
      content: { title: "Main" },
    },
    {
      id: "r3",
      number: 3,
      parent_id: "r1",
      branch_id: "other",
      content: { title: "Other" },
    },
  ];
  const before = structuredClone(revisions);
  const branches = [
    { id: "main", head_revision: "r2" },
    { id: "other", head_revision: "r3" },
  ];
  const working = [
    {
      base_revision: "r2",
      content: { title: "Edited main" },
      updated_at: "2026-09-13",
    },
    {
      base_revision: "r3",
      content: { title: "Edited other" },
      updated_at: "2026-09-13",
    },
  ];
  const graph = historyGraph(revisions, branches, working);
  assert.deepEqual(
    graph.nodes.map(/* 提取显示节点，草稿紧邻所属基线 */ (n) => n.revision.id),
    ["working:r3", "r3", "working:r2", "r2", "r1"],
  );
  assert.deepEqual(
    graph.edges
      .filter(/* 提取虚线草稿边 */ (edge) => edge.uncommitted)
      .map(/* 检查准确的基线连接 */ (edge) => [edge.from, edge.to]),
    [
      ["working:r3", "r3"],
      ["working:r2", "r2"],
    ],
  );
  assert.equal(graph.nodes[0].revision.content.title, "Edited other");
  assert.equal(graph.nodes[1].revision.content.title, "Other");
  assert.deepEqual(revisions, before);
  const savedOnly = historyGraph(revisions, branches);
  assert.equal(savedOnly.nodes.length, 3);
  assert.equal(
    savedOnly.nodes.some(
      /* 提交后不再展示草稿节点 */ (n) => n.revision.uncommitted,
    ),
    false,
  );
});

test("history graph follows actual parents across interleaved branches", /* 验证交错保存和旧分叉仍按真实父关系连线 */ () => {
  const revisions = [
    { id: "r1", number: 1, parent_id: null, branch_id: "main" },
    { id: "r2", number: 2, parent_id: "r1", branch_id: "main" },
    { id: "r3", number: 3, parent_id: "r1", branch_id: "backend" },
    { id: "r4", number: 4, parent_id: "r2", branch_id: "main" },
    { id: "r5", number: 5, parent_id: "r3", branch_id: "backend" },
  ];
  const graph = historyGraph(revisions, [{ id: "main" }, { id: "backend" }]);
  assert.deepEqual(
    graph.nodes.map(/* 提取显示顺序 */ (node) => node.revision.id),
    ["r5", "r4", "r3", "r2", "r1"],
  );
  assert.deepEqual(
    graph.edges.map(
      /* 核对版本节点的父子关系 */ (edge) => [edge.from, edge.to],
    ),
    [
      ["r5", "r3"],
      ["r4", "r2"],
      ["r3", "r1"],
      ["r2", "r1"],
    ],
  );
  assert.equal(graph.nodes[0].x, graph.nodes[2].x);
  assert.notEqual(graph.nodes[0].x, graph.nodes[1].x);
  assert.deepEqual(
    revisions.map(/* 原始数据不可被排序器修改 */ (revision) => revision.id),
    ["r1", "r2", "r3", "r4", "r5"],
  );
});

test("revision summary distinguishes metadata, edits and deleted highlights", /* 验证变更摘要可准确解释版本差异 */ () => {
  const content = {
    title: "Demo",
    period: "",
    role: "",
    stack: [],
    description: "",
    highlights: [
      { id: "a", text: "old" },
      { id: "b", text: "remove" },
    ],
  };
  const next = {
    content: {
      ...content,
      title: "Backend",
      highlights: [
        { id: "a", text: "new" },
        { id: "c", text: "added" },
      ],
    },
  };
  assert.deepEqual(revisionChanges(next, { content }), [
    "项目标题",
    "新增 1 条亮点",
    "修改 1 条亮点",
    "删除 1 条亮点",
  ]);
  assert.deepEqual(revisionChanges({ content }, { content }), ["经历内容未变"]);
});
