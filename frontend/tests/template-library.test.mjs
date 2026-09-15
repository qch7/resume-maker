import { test } from "node:test";
import assert from "node:assert/strict";
import {
  filterTemplates,
  libraryTemplates,
} from "../src/shared/components/template-library/library.ts";

test("新模板和内置模板默认未分类，失效分类也回到未分类", () => {
  const items = libraryTemplates(
    [{ id: "one", name: "设计", created_at: "2026-09-15" }],
    { categories: [], items: { one: { category_id: "deleted", liked: true } } },
  );
  assert.equal(items[0].id, "builtin");
  assert.ok(items.every((item) => item.category_id === ""));
  assert.equal(items[0].liked, false);
  assert.equal(items[1].liked, true);
});

test("分类与名称联合搜索、跨分类 Like 和保存日期排序共用一致结果", () => {
  const items = libraryTemplates(
    [
      { id: "one", name: "React 简历", created_at: "2026-09-15" },
      { id: "two", name: "React 简洁", created_at: "2026-09-12" },
      { id: "three", name: "设计", created_at: "2026-09-14" },
    ],
    {
      categories: [{ id: "tech", name: "技术" }],
      items: {
        one: { category_id: "tech", liked: true },
        three: { category_id: "", liked: true },
      },
    },
  );
  assert.deepEqual(
    filterTemplates(items, "tech", " REACT ", "name").map((item) => item.id),
    ["one"],
  );
  assert.deepEqual(
    filterTemplates(items, "liked", "", "newest").map((item) => item.id),
    ["one", "three"],
  );
  assert.deepEqual(
    filterTemplates(items, "", "react", "name").map((item) => item.id),
    ["two"],
  );
  assert.equal(filterTemplates(items, "all", "无匹配", "name").length, 0);
});
