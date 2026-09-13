import { test } from "node:test";
import assert from "node:assert/strict";
import {
  restoreSidebarSort,
  sortSidebar,
  expandProjectPath,
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

test("child activity brings its aggregate forward and navigation expands its ancestors", /* 验证子项目活动参与整体排序，并保留其他分组的折叠选择。 */ () => {
  const rows = [
    { id: "parent", name: "TrustGuard", updated_at: "2026-09-01T00:00:00Z" },
    {
      id: "child",
      parent_id: "parent",
      name: "agent",
      updated_at: "2026-09-02T00:00:00Z",
    },
    { id: "other", name: "独立项目", updated_at: "2026-09-03T00:00:00Z" },
  ];
  const sessions = [
    {
      id: "chat",
      project_id: "child",
      title: "子项目会话",
      updated_at: "2026-09-05T00:00:00Z",
    },
  ];
  const roots = sortSidebar(rows, sessions, "recent").projects.filter(
    /* 只比较顶层整体项目。 */ (p) => !p.parent_id,
  );
  assert.deepEqual(
    roots.map(/* 提取排序标识。 */ (p) => p.id),
    ["parent", "other"],
  );
  const folded = { parent: true, child: true, other: true };
  assert.deepEqual(expandProjectPath(rows, "child", folded), {
    parent: false,
    child: false,
    other: true,
  });
  assert.deepEqual(folded, { parent: true, child: true, other: true });
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
