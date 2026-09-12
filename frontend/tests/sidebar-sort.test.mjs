import { test } from "node:test";
import assert from "node:assert/strict";
import {
  restoreSidebarSort,
  sortSidebar,
} from "../src/features/projects/sort.ts";

const projects = [
  { id: "a", name: "alpha", updated_at: "2026-09-01T00:00:00Z" },
  { id: "b", name: "Beta 10", updated_at: "2026-09-03T00:00:00Z" },
  { id: "c", name: "beta 2", updated_at: "2026-09-02T00:00:00Z" },
];
const conversations = [
  {
    id: "first",
    project_id: "a",
    title: "会话 10",
    updated_at: "2026-09-05T00:00:00Z",
  },
  {
    id: "second",
    project_id: "a",
    title: "会话 2",
    updated_at: "2026-09-04T00:00:00Z",
  },
];

test("alphabetic mode sorts projects and conversations naturally in both directions", /* 验证项目和会话支持自然名称正序与倒序。 */ () => {
  const asc = sortSidebar(projects, conversations, "asc");
  assert.deepEqual(
    asc.projects.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (p) => p.id,
    ),
    ["a", "c", "b"],
  );
  assert.deepEqual(
    asc.conversations.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (c) => c.id,
    ),
    ["second", "first"],
  );
  const desc = sortSidebar(projects, conversations, "desc");
  assert.deepEqual(
    desc.projects.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (p) => p.id,
    ),
    ["b", "c", "a"],
  );
  assert.deepEqual(
    desc.conversations.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (c) => c.id,
    ),
    ["first", "second"],
  );
  assert.deepEqual(
    projects.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (p) => p.id,
    ),
    ["a", "b", "c"],
  );
});

test("recent mode includes project edits, drafts and conversation activity", /* 验证最近排序包含项目修改、草稿和会话活动。 */ () => {
  assert.deepEqual(
    sortSidebar(projects, [], "recent").projects.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (p) => p.id,
    ),
    ["b", "c", "a"],
  );
  assert.deepEqual(
    sortSidebar(projects, conversations, "recent").projects.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (p) => p.id,
    ),
    ["a", "b", "c"],
  );
  const changed = projects.map(
    /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (p) =>
      p.id === "c" ? { ...p, activity_at: "2026-09-06T00:00:00Z" } : p,
  );
  assert.deepEqual(
    sortSidebar(changed, conversations, "recent").projects.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (p) => p.id,
    ),
    ["c", "a", "b"],
  );
  assert.equal(
    sortSidebar(changed, conversations, "recent").conversations[0].id,
    "first",
  );
});

test("missing timestamps and equal names have deterministic ordering", /* 验证缺失时间和重名条目仍有确定的排序。 */ () => {
  const rows = [
    { id: "2", name: "Same", updated_at: "invalid" },
    { id: "1", name: "same" },
  ];
  assert.deepEqual(
    sortSidebar(rows, [], "recent").projects.map(
      /* 提取排序后的稳定标识，验证顺序且不依赖对象引用。 */ (p) => p.id,
    ),
    ["1", "2"],
  );
  assert.equal(restoreSidebarSort("desc"), "desc");
  assert.equal(restoreSidebarSort("invalid"), "recent");
});
