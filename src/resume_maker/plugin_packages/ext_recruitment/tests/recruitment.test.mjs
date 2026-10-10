import assert from "node:assert/strict";
import test from "node:test";
import { readImportFile } from "../client/importFile.ts";
import {
  bookmarkDescription,
  filterBookmarks,
  newBookmark,
  restoreDisplayPreferences,
  restoreSidebarWidth,
  scopeCategories,
  sortBookmarks,
} from "../client/model.ts";

test("招聘侧栏恢复有效宽度，损坏及越界偏好保持可用", () => {
  assert.equal(restoreSidebarWidth(320), 320);
  assert.equal(restoreSidebarWidth(40), 160);
  assert.equal(restoreSidebarWidth(2000), 520);
  for (const value of [undefined, null, "wide", NaN, Infinity])
    assert.equal(restoreSidebarWidth(value), 210);
});

test("标签已经包含的描述只展示一次，保留原数据及标签搜索", () => {
  const item = {
    ...newBookmark("internet"),
    description: "网络安全、浏览器、AI",
    tags: ["网络安全", "浏览器", "AI"],
  };
  const original = structuredClone(item);
  assert.equal(bookmarkDescription(item), "");
  assert.equal(
    bookmarkDescription({ ...item, description: " ai，浏览器；网络安全 " }),
    "",
  );
  assert.equal(bookmarkDescription({ ...item, description: "网络安全" }), "");
  assert.deepEqual(filterBookmarks([item], "", "", false, "网络安全"), [item]);
  assert.deepEqual(item, original);
});

test("有额外信息或没有标签时保留完整描述，避免按子串误删", () => {
  const item = { ...newBookmark("internet"), tags: ["AI"] };
  for (const description of [
    "AI，支持远程实习",
    "AI 研发",
    "AI/机器人",
    "招聘官网",
  ]) {
    assert.equal(bookmarkDescription({ ...item, description }), description);
  }
  assert.equal(
    bookmarkDescription({ ...item, description: "AI", tags: [] }),
    "AI",
  );
  assert.equal(bookmarkDescription({ ...item, description: "" }), "");
});

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

test("全部网站显示空分类，领域只显示各自使用的分类并保留分类顺序", () => {
  const categories = [
    { id: "shared", name: "共同分类" },
    { id: "internet-only", name: "互联网分类" },
    { id: "technology-only", name: "科技分类" },
    { id: "empty", name: "尚无网址" },
  ];
  const items = [
    { ...newBookmark("internet"), category: "internet-only" },
    { ...newBookmark("technology"), category: "technology-only" },
    { ...newBookmark("internet"), category: "shared" },
    { ...newBookmark("technology"), category: "shared" },
    newBookmark("empty-domain"),
  ];
  assert.deepEqual(scopeCategories(categories, items, "", false), categories);
  assert.deepEqual(scopeCategories(categories, items, "internet", false), [
    categories[0],
    categories[1],
  ]);
  assert.deepEqual(scopeCategories(categories, items, "technology", false), [
    categories[0],
    categories[2],
  ]);
  assert.deepEqual(
    scopeCategories(categories, items, "empty-domain", false),
    [],
  );
  assert.deepEqual(scopeCategories(categories, [], "internet", false), []);
});

test("星标分类来自跨领域的星标条目，取消最后一个星标后分类退出当前范围", () => {
  const categories = [
    { id: "large", name: "大厂" },
    { id: "medium", name: "中厂" },
    { id: "small", name: "小厂" },
  ];
  const items = [
    { ...newBookmark("internet"), category: "large", favorite: true },
    { ...newBookmark("technology"), category: "small", favorite: true },
    { ...newBookmark("internet"), category: "medium" },
    { ...newBookmark("technology"), favorite: true },
  ];
  assert.deepEqual(scopeCategories(categories, items, "", true), [
    categories[0],
    categories[2],
  ]);
  assert.deepEqual(scopeCategories(categories, items, "internet", true), [
    categories[0],
  ]);
  const changed = items.map((item) => ({
    ...item,
    favorite: item.category !== "large" && item.favorite,
  }));
  assert.deepEqual(scopeCategories(categories, changed, "", true), [
    categories[2],
  ]);
  assert.deepEqual(scopeCategories(categories, changed, "internet", true), []);
  assert.deepEqual(scopeCategories(categories, [], "", true), []);
});

test("默认顺序按 JSON 位置排列星标及普通条目，取消星标恢复原位置", () => {
  const items = ["Zulu", "Delta", "Alpha", "Beta"].map((name, index) => ({
    ...newBookmark("one"),
    name,
    favorite: index === 1 || index === 3,
  }));
  const original = structuredClone(items);
  assert.deepEqual(sortBookmarks(items, "default"), [
    items[1],
    items[3],
    items[0],
    items[2],
  ]);
  const unstarred = items.map((item) => ({ ...item, favorite: false }));
  assert.deepEqual(sortBookmarks(unstarred, "default"), unstarred);
  assert.deepEqual(items, original);
});

test("字母升降序均将星标置顶，同名稳定排序且不改变导出顺序", () => {
  const items = ["Zulu", "Delta", "alpha", "Beta", "Alpha"].map(
    (name, index) => ({
      ...newBookmark("one"),
      name,
      favorite: index === 1 || index === 3,
    }),
  );
  const original = structuredClone(items);
  assert.deepEqual(sortBookmarks(items, "asc"), [
    items[3],
    items[1],
    items[2],
    items[4],
    items[0],
  ]);
  assert.deepEqual(sortBookmarks(items, "desc"), [
    items[1],
    items[3],
    items[0],
    items[2],
    items[4],
  ]);
  assert.deepEqual(items, original);
});

test("中文名称按拼音排序，筛选后保持星标优先和范围隔离", () => {
  const items = ["腾讯", "百度", "阿里", "字节"].map((name, index) => ({
    ...newBookmark(index === 3 ? "other" : "internet"),
    name,
    favorite: index === 0,
  }));
  const filtered = filterBookmarks(items, "internet", "", false, "");
  assert.deepEqual(sortBookmarks(filtered, "asc"), [
    items[0],
    items[2],
    items[1],
  ]);
  assert.deepEqual(sortBookmarks(filtered, "desc"), [
    items[0],
    items[1],
    items[2],
  ]);
});

test("恢复卡片或列表和排序偏好，失效设置回退默认显示", () => {
  assert.deepEqual(restoreDisplayPreferences({ view: "list", sort: "desc" }), {
    view: "list",
    sort: "desc",
  });
  assert.deepEqual(restoreDisplayPreferences({ view: "cards", sort: "asc" }), {
    view: "cards",
    sort: "asc",
  });
  for (const invalid of [
    null,
    undefined,
    "list",
    {},
    { view: "table", sort: "name" },
  ]) {
    assert.deepEqual(restoreDisplayPreferences(invalid), {
      view: "cards",
      sort: "default",
    });
  }
});

test("选择或拖放单个 JSON 保留 UTF-8 内容，取消选择不改变文件", async () => {
  const content = '{"name":"招聘清单"}';
  const file = new File([content], "list.JSON", { type: "application/json" });
  assert.deepEqual(await readImportFile([file]), {
    name: "list.JSON",
    content,
  });
  assert.equal(await readImportFile([]), null);
});

test("拖入多文件、错误类型、超限或空文件时拒绝读取导入", async () => {
  const file = new File(["{}"], "list.json");
  await assert.rejects(readImportFile([file, file]), /一个文件/);
  await assert.rejects(readImportFile([new File(["{}"], "list.txt")]), /JSON/);
  await assert.rejects(
    readImportFile([new File([" \n"], "empty.json")]),
    /为空/,
  );
  await assert.rejects(
    readImportFile([new File([new Uint8Array(8_000_001)], "large.json")]),
    /8 MB/,
  );
});
