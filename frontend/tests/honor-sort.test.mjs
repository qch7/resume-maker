import { test } from "node:test";
import assert from "node:assert/strict";
import {
  nextHonorSort,
  sortHonors,
  sortHonorEntries,
} from "../src/features/honors/sort.ts";
import { newHonorEntry } from "../src/features/honors/entry.ts";
import { emptyHonor } from "../src/features/honors/fields.ts";

const honors = [
  {
    id: "one",
    fields: { ...emptyHonor(), name: "证书 10", date: "2025年12月" },
    updated_at: "2026-09-03T00:00:00Z",
  },
  {
    id: "two",
    fields: { ...emptyHonor(), name: "证书 2", date: "2026/2/3" },
    updated_at: "2026-09-01T00:00:00Z",
  },
  {
    id: "three",
    fields: { ...emptyHonor(), name: "证书 1", date: "2025-6" },
    updated_at: "2026-09-02T00:00:00Z",
  },
];
/** 提取条目标识用于核对排序 */
const ids = (rows) => rows.map(/* 保留稳定引用身份 */ (item) => item.id);

test("all three honor sort buttons reverse their own order", /* 三种维度各有独立的正倒序，切换维度使用适合字段的初始方向 */ () => {
  for (const key of ["recent", "date", "name"]) {
    const initial = nextHonorSort(null, key);
    assert.equal(initial.direction, key === "name" ? "asc" : "desc");
    assert.notEqual(nextHonorSort(initial, key).direction, initial.direction);
    assert.deepEqual(nextHonorSort(nextHonorSort(initial, key), key), initial);
  }
  assert.deepEqual(nextHonorSort({ key: "name", direction: "desc" }, "date"), {
    key: "date",
    direction: "desc",
  });
  const before = structuredClone(honors);
  for (const [key, expected] of [
    ["recent", ["two", "three", "one"]],
    ["date", ["three", "one", "two"]],
    ["name", ["three", "two", "one"]],
  ]) {
    assert.deepEqual(
      ids(sortHonors(honors, { key, direction: "asc" })),
      expected,
    );
    assert.deepEqual(
      ids(sortHonors(honors, { key, direction: "desc" })),
      [...expected].reverse(),
    );
  }
  assert.deepEqual(honors, before);
});

test("missing and invalid dates stay last while equal dates retain manual order", /* 中文日期和不同精度日期按日历比较，空值不随倒序跑到最前面 */ () => {
  const rows = [
    { ...honors[0], id: "blank", fields: { ...honors[0].fields, date: "" } },
    {
      ...honors[0],
      id: "equal-a",
      fields: { ...honors[0].fields, date: "2025.12.1" },
    },
    {
      ...honors[0],
      id: "invalid",
      fields: { ...honors[0].fields, date: "2025-02-30" },
    },
    {
      ...honors[0],
      id: "equal-b",
      fields: { ...honors[0].fields, date: "2025年12月" },
    },
    honors[1],
  ];
  assert.deepEqual(ids(sortHonors(rows, { key: "date", direction: "asc" })), [
    "equal-a",
    "equal-b",
    "two",
    "blank",
    "invalid",
  ]);
  assert.deepEqual(ids(sortHonors(rows, { key: "date", direction: "desc" })), [
    "two",
    "equal-a",
    "equal-b",
    "blank",
    "invalid",
  ]);
});

test("organizer sorting preserves complete entries and unrelated positions", /* 调整实际简历顺序时保留来源引用、隐藏资料、自定义字段及混合栏目中的普通条目 */ () => {
  const entries = honors.map(
    /* 和库来源关联，日期和名称由当前简历提供 */ (honor) =>
      newHonorEntry(honor.fields, `honor:${honor.id}`),
  );
  entries[0].visible = false;
  entries[1].period = "2027-01";
  const manual = newHonorEntry(emptyHonor(), "honor:manual:one");
  const other = { ...manual, id: "ordinary", title: "普通资料" };
  const section = {
    id: "custom",
    title: "自定义成果",
    kind: "text",
    entries: [entries[0], other, manual, entries[1], entries[2]],
  };
  const before = structuredClone(section);
  const result = sortHonorEntries(section, honors, {
    key: "recent",
    direction: "asc",
  });
  assert.deepEqual(ids(result), [
    "honor:two",
    "ordinary",
    "honor:three",
    "honor:one",
    "honor:manual:one",
  ]);
  assert.equal(result[1], other);
  assert.equal(result[3], entries[0]);
  assert.equal(result[3].visible, false);
  assert.equal(
    sortHonorEntries(section, honors, { key: "date", direction: "desc" })[0],
    entries[1],
  );
  assert.deepEqual(section, before);
  assert.deepEqual(
    ids(sortHonorEntries(section, [], { key: "recent", direction: "desc" })),
    ids(section.entries),
  );
});
