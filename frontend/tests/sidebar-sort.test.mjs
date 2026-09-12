import { test } from "node:test";
import assert from "node:assert/strict";
import { restoreSidebarSort, sortSidebar } from "../src/sidebarSort.ts";

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

test("alphabetic mode sorts projects and conversations naturally in both directions", () => {
  const asc = sortSidebar(projects, conversations, "asc");
  assert.deepEqual(
    asc.projects.map((p) => p.id),
    ["a", "c", "b"],
  );
  assert.deepEqual(
    asc.conversations.map((c) => c.id),
    ["second", "first"],
  );
  const desc = sortSidebar(projects, conversations, "desc");
  assert.deepEqual(
    desc.projects.map((p) => p.id),
    ["b", "c", "a"],
  );
  assert.deepEqual(
    desc.conversations.map((c) => c.id),
    ["first", "second"],
  );
  assert.deepEqual(
    projects.map((p) => p.id),
    ["a", "b", "c"],
  );
});

test("recent mode includes project edits, drafts and conversation activity", () => {
  assert.deepEqual(
    sortSidebar(projects, [], "recent").projects.map((p) => p.id),
    ["b", "c", "a"],
  );
  assert.deepEqual(
    sortSidebar(projects, conversations, "recent").projects.map((p) => p.id),
    ["a", "b", "c"],
  );
  const changed = projects.map((p) =>
    p.id === "c" ? { ...p, activity_at: "2026-09-06T00:00:00Z" } : p,
  );
  assert.deepEqual(
    sortSidebar(changed, conversations, "recent").projects.map((p) => p.id),
    ["c", "a", "b"],
  );
  assert.equal(
    sortSidebar(changed, conversations, "recent").conversations[0].id,
    "first",
  );
});

test("missing timestamps and equal names have deterministic ordering", () => {
  const rows = [
    { id: "2", name: "Same", updated_at: "invalid" },
    { id: "1", name: "same" },
  ];
  assert.deepEqual(
    sortSidebar(rows, [], "recent").projects.map((p) => p.id),
    ["1", "2"],
  );
  assert.equal(restoreSidebarSort("desc"), "desc");
  assert.equal(restoreSidebarSort("invalid"), "recent");
});
