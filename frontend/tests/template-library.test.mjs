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

test("回收站与分类收藏隔离，恢复后回到原分类，服务器列表可清除过期模板", () => {
  const templates = [
    { id: "one", name: "待删除", created_at: "2026-09-15" },
    { id: "two", name: "保留", created_at: "2026-09-14" },
  ];
  const state = {
    categories: [{ id: "tech", name: "技术" }],
    items: {
      one: {
        category_id: "tech",
        liked: true,
        deleted_at: "2026-09-17T00:00:00Z",
      },
    },
  };
  let items = libraryTemplates(templates, state);
  assert.deepEqual(
    filterTemplates(items, "trash", "", "name").map((item) => item.id),
    ["one"],
  );
  for (const folder of ["all", "liked", "tech", ""]) {
    assert.ok(
      filterTemplates(items, folder, "", "name").every(
        (item) => item.id !== "one",
      ),
    );
  }
  delete state.items.one.deleted_at;
  items = libraryTemplates(templates, state);
  assert.equal(filterTemplates(items, "trash", "", "name").length, 0);
  assert.equal(filterTemplates(items, "tech", "", "name")[0].liked, true);
  items = libraryTemplates(templates, {
    ...state,
    templates: [{ ...templates[1], usage_count: 2 }],
  });
  assert.ok(items.every((item) => item.id !== "one"));
  assert.equal(items.find((item) => item.id === "two").usage_count, 2);
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
