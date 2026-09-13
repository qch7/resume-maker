import { test } from "node:test";
import assert from "node:assert/strict";
import {
  normalizeHighlightOrder,
  orderedHighlightIds,
  toggleHighlightSelection,
} from "../src/features/resumes/composition.ts";

const highlights = [
  { id: "evidence", title: "证据研判", text: "证据研判内容", evidence: [] },
  { id: "tasks", title: "任务编排", text: "任务编排内容", evidence: [] },
  { id: "mcp", title: "MCP 接入", text: "MCP 接入内容", evidence: [] },
  { id: "audit", title: "权限审计", text: "权限审计内容", evidence: [] },
];
const originalOrder = ["evidence", "tasks", "mcp", "audit"];

test("rechecking any highlight restores its experience position", /* 验证首项、中间项和末项重新勾选后均回到原位。 */ () => {
  for (const id of originalOrder) {
    const unchecked = toggleHighlightSelection(highlights, originalOrder, id);
    assert.equal(unchecked.includes(id), false);
    const checked = toggleHighlightSelection(highlights, unchecked, id);
    assert.deepEqual(checked, originalOrder);
  }
  assert.deepEqual(originalOrder, ["evidence", "tasks", "mcp", "audit"]);
});

test("partial and empty selections keep experience order regardless of click order", /* 验证任意勾选顺序、部分选择和全部取消不会改变经历顺序。 */ () => {
  let selected = [];
  for (const id of ["audit", "tasks", "evidence"])
    selected = toggleHighlightSelection(highlights, selected, id);
  assert.deepEqual(selected, ["evidence", "tasks", "audit"]);
  selected = toggleHighlightSelection(highlights, selected, "tasks");
  assert.deepEqual(selected, ["evidence", "audit"]);
  for (const id of ["audit", "evidence"])
    selected = toggleHighlightSelection(highlights, selected, id);
  assert.deepEqual(selected, []);
});

test("applying a reordered revision preserves the selected subset in the new order", /* 验证显式更新版本后采用新顺序，不选中新亮点或恢复已取消的亮点。 */ () => {
  const next = [
    highlights[3],
    highlights[2],
    { id: "new", title: "新增亮点", text: "新增内容", evidence: [] },
    highlights[0],
  ];
  const selected = orderedHighlightIds(next, ["evidence", "tasks", "audit"]);
  assert.deepEqual(selected, ["audit", "evidence"]);
  assert.deepEqual(orderedHighlightIds(next, []), []);
});

test("cached compositions normalize per pinned revision without moving projects or mutating input", /* 验证旧缓存错序被修复，项目顺序和固定版本保持不变。 */ () => {
  const draft = {
    id: "resume",
    name: "顺序回归简历",
    template_id: null,
    version: 3,
    items: [
      { project_id: "other", revision_id: "unloaded", highlight_ids: ["x"] },
      {
        project_id: "project",
        revision_id: "pinned",
        highlight_ids: ["evidence", "mcp", "audit", "tasks"],
      },
    ],
  };
  const before = structuredClone(draft);
  const revisions = {
    pinned: { id: "pinned", project_id: "project", content: { highlights } },
    latest: {
      id: "latest",
      project_id: "project",
      content: { highlights: highlights.toReversed() },
    },
  };
  const normalized = normalizeHighlightOrder(draft, revisions);
  assert.deepEqual(normalized, {
    ...draft,
    items: [
      draft.items[0],
      { ...draft.items[1], highlight_ids: originalOrder },
    ],
  });
  assert.deepEqual(draft, before);
  assert.equal(normalized.items[0], draft.items[0]);
  assert.equal(normalizeHighlightOrder(normalized, revisions), normalized);

  const restored = JSON.parse(JSON.stringify(normalized));
  assert.deepEqual(normalizeHighlightOrder(restored, revisions), normalized);
});

test("an unloaded pinned revision retains all selections until its cache arrives", /* 验证缓存异步加载时不清空选择，空选择也不会自动全选。 */ () => {
  const draft = {
    items: [
      {
        project_id: "project",
        revision_id: "pinned",
        highlight_ids: ["audit", "tasks"],
      },
      { project_id: "empty", revision_id: "empty", highlight_ids: [] },
    ],
  };
  assert.equal(normalizeHighlightOrder(draft, {}), draft);
  const normalized = normalizeHighlightOrder(draft, {
    pinned: { content: { highlights } },
    empty: { content: { highlights } },
  });
  assert.deepEqual(normalized.items[0].highlight_ids, ["tasks", "audit"]);
  assert.deepEqual(normalized.items[1].highlight_ids, []);
});
