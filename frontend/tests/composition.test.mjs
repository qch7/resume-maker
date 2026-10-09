import { test } from "node:test";
import assert from "node:assert/strict";
import {
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

test("rechecking any highlight restores its experience position", /* 验证首项、中间项和末项重新勾选后均回到原位 */ () => {
  for (const id of originalOrder) {
    const unchecked = toggleHighlightSelection(highlights, originalOrder, id);
    assert.equal(unchecked.includes(id), false);
    const checked = toggleHighlightSelection(highlights, unchecked, id);
    assert.deepEqual(checked, originalOrder);
  }
  assert.deepEqual(originalOrder, ["evidence", "tasks", "mcp", "audit"]);
});

test("partial and empty selections keep experience order regardless of click order", /* 验证任意勾选顺序、部分选择和全部取消不会改变经历顺序 */ () => {
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

test("applying a reordered revision preserves the selected subset in the new order", /* 更新版本后沿用新顺序并保留原有亮点选择 */ () => {
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
