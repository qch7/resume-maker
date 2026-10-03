import assert from "node:assert/strict";
import test from "node:test";
import {
  filterBookmarks,
  moveBookmark,
  newBookmark,
} from "../src/features/recruitment/model.ts";

test("按领域、企业分类和收藏筛选，搜索同时覆盖备注及链接", () => {
  const first = {
    ...newBookmark("internet"),
    name: "示例公司",
    category: "large",
    favorite: true,
    notes: "关注杭州实习",
    links: [{ label: "校园招聘", url: "https://example.com/jobs" }],
  };
  const second = {
    ...newBookmark("custom"),
    name: "自定义公司",
    category: "priority",
  };
  assert.deepEqual(
    filterBookmarks(
      [first, second],
      "internet",
      "large",
      true,
      "杭州 example.com",
    ),
    [first],
  );
  assert.deepEqual(
    filterBookmarks([first, second], "custom", "priority", false, "自定义"),
    [second],
  );
  assert.deepEqual(
    filterBookmarks([first, second], "internet", "small", false, ""),
    [],
  );
});

test("新收藏不附带任何默认领域或分类", () => {
  const item = newBookmark("");
  assert.equal(item.domain_id, "");
  assert.equal(item.category, "");
});

test("过滤后排序只交换可见邻居，保留其他领域和原始数组", () => {
  const items = [newBookmark("one"), newBookmark("two"), newBookmark("one")];
  const original = structuredClone(items);
  const visible = [items[0], items[2]];
  assert.deepEqual(moveBookmark(items, visible, items[2].id, -1), [
    items[2],
    items[1],
    items[0],
  ]);
  assert.deepEqual(moveBookmark(items, visible, items[0].id, -1), items);
  assert.deepEqual(items, original);
});
