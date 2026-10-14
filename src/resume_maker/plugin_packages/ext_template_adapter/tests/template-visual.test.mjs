import { test } from "node:test";
import assert from "node:assert/strict";
import {
  siblingRange,
  descendants,
  mappingIndex,
  highlightedText,
  clearNodes,
  repeatNodes,
  templateChildren,
} from "../client/visual.ts";
import {
  templateSnapshot,
  templateSelection,
} from "../client/visualSnapshot.ts";

/** 构造包含多个单元格、图片、页眉的脱敏模板结构 */
function fixture() {
  /** 为每个位置明确记录其直接容器、可见祖先 */
  function node(
    id,
    kind,
    parent,
    ancestors = [],
    text = "",
    part = "word/document.xml",
  ) {
    return {
      id,
      kind,
      parent,
      ancestors,
      text,
      part,
      can_insert: kind === "p" && !text,
    };
  }
  return [
    node("name", "p", "body", [], "姓名：示例"),
    node("table", "tbl", "body", [], "表格文字"),
    node("row1", "tr", "table", ["table"]),
    node("school", "p", "cell1", ["row1", "table"], "示例大学"),
    node("degree", "p", "cell2", ["row1", "table"], "本科"),
    node("row2", "tr", "table", ["table"]),
    node("other", "p", "cell3", ["row2", "table"], "旧大学"),
    node("picture", "p", "body"),
    node("photo", "image", "drawing", ["picture"], "照片"),
    node("header", "p", "head", [], "页眉", "word/header1.xml"),
  ];
}

/** 生成包含一条教育样本、两行原文的模板映射 */
function plan() {
  return {
    summary: "测试",
    fields: [
      { node: "name", quote: "示例", target: "personal.name", occurrence: 1 },
    ],
    repeats: [
      {
        section: "教育经历",
        start: "row1",
        end: "row2",
        sample_start: "row1",
        sample_end: "row1",
        fields: [
          { node: "school", quote: "示例大学", target: "title", occurrence: 1 },
        ],
      },
    ],
    photos: ["photo"],
    keep: ["header"],
    remove: [],
    warnings: [],
  };
}

test("结构索引保留最近可见祖先、部件及原始顺序", () => {
  const nodes = fixture();
  const before = structuredClone(nodes);
  const children = templateChildren(nodes);
  assert.deepEqual(
    children.get("word/document.xml").map((node) => node.id),
    ["name", "table", "picture"],
  );
  assert.deepEqual(
    children.get("table").map((node) => node.id),
    ["row1", "row2"],
  );
  assert.deepEqual(
    children.get("row1").map((node) => node.id),
    ["school", "degree"],
  );
  assert.deepEqual(
    children.get("picture").map((node) => node.id),
    ["photo"],
  );
  assert.deepEqual(
    children.get("word/header1.xml").map((node) => node.id),
    ["header"],
  );
  assert.deepEqual(nodes, before);
});

test("同级范围按原文排序，跨单元格、跨部件和图片范围不能拼接", /* 用户反向点击仍选取完整闭区间 */ () => {
  const nodes = fixture();
  assert.deepEqual(siblingRange(nodes, "row2", "row1"), ["row1", "row2"]);
  assert.deepEqual(siblingRange(nodes, "name", "picture"), [
    "name",
    "table",
    "picture",
  ]);
  for (const [start, end] of [
    ["school", "degree"],
    ["header", "name"],
    ["missing", "name"],
    ["photo", "photo"],
  ])
    assert.deepEqual(siblingRange(nodes, start, end), []);
});

test("选择表格行或图片容器时包含全部后代，单条样本不包含第二条示例", /* 层级选择不能漏掉单元格或内嵌图片 */ () => {
  const nodes = fixture();
  assert.deepEqual(descendants(nodes, ["row1"]), ["row1", "school", "degree"]);
  assert.deepEqual(descendants(nodes, ["picture"]), ["picture", "photo"]);
  assert.deepEqual(repeatNodes(nodes, plan(), 0, true), [
    "row1",
    "school",
    "degree",
  ]);
  assert.deepEqual(repeatNodes(nodes, plan(), 0), [
    "row1",
    "school",
    "degree",
    "row2",
    "other",
  ]);
});

test("字段、重复示例、照片和删除容器呈现不同用途", /* 删除优先级必须覆盖内部字段、照片，容器不误报待处理 */ () => {
  const nodes = fixture(),
    value = plan();
  const index = mappingIndex(nodes, value);
  assert.equal(index.get("table").kind, "container");
  assert.equal(index.get("school").kind, "field");
  assert.equal(index.get("school").region, 0);
  assert.equal(index.get("other").kind, "repeat");
  assert.equal(index.get("photo").kind, "photo");
  assert.equal(index.get("header").kind, "keep");
  assert.equal(
    mappingIndex(nodes, { ...value, remove: ["picture"] }).get("photo").kind,
    "remove",
  );
});

test("精确引文高亮尊重出现次数和标签，错误引文不制造虚假字段", /* 同段相同值只高亮指定的一次 */ () => {
  const fields = [
    { node: "n", quote: "示例", target: "personal.name", occurrence: 2 },
  ];
  assert.deepEqual(highlightedText("示例 / 姓名：示例", fields), [
    { text: "示例 / 姓名：" },
    { text: "示例", target: "personal.name" },
  ]);
  assert.deepEqual(highlightedText("原文未匹配", fields), [
    { text: "原文未匹配" },
  ]);
  assert.deepEqual(
    highlightedText("", [{ ...fields[0], quote: "", occurrence: 1 }]),
    [],
  );
});

test("重新分类撤销覆盖当前节点的删除标记，保留其他区域和重复方案", /* 手工调整照片不误删姓名、页眉或教育映射 */ () => {
  const value = { ...plan(), remove: ["picture", "other"] };
  const cleared = clearNodes(value, fixture(), ["photo"]);
  assert.deepEqual(cleared.photos, []);
  assert.deepEqual(cleared.remove, ["other"]);
  assert.deepEqual(cleared.keep, ["header"]);
  assert.deepEqual(cleared.fields, value.fields);
  assert.deepEqual(cleared.repeats, value.repeats);
  assert.deepEqual(value.photos, ["photo"]);
});

test("共享选区索引保留全部区域归属、样本限制及文档顺序", () => {
  const nodes = fixture();
  const value = plan();
  value.repeats.push({
    ...value.repeats[0],
    section: "重叠栏目",
    start: "row2",
    end: "row2",
    sample_start: "row2",
    sample_end: "row2",
    fields: [],
  });
  const before = structuredClone({ nodes, value });
  const snapshot = templateSnapshot(nodes, value);
  assert.deepEqual(snapshot.mappings, mappingIndex(nodes, value));
  assert.deepEqual(snapshot.children, templateChildren(nodes));
  const sample = templateSelection(snapshot, ["row1"]);
  assert.equal(sample.info, snapshot.mappings.get("row1"));
  assert.deepEqual(sample.touched, [true, false]);
  assert.equal(sample.inSample, true);
  assert.deepEqual(
    sample.fields.map((field) => field.node),
    ["school"],
  );
  assert.deepEqual(
    sample.available.map((node) => node.id),
    ["school", "degree"],
  );
  const overlap = templateSelection(snapshot, ["row2"]);
  assert.deepEqual(snapshot.memberships.get("other"), [0, 1]);
  assert.equal(overlap.info.region, 0);
  assert.deepEqual(overlap.touched, [true, true]);
  assert.equal(overlap.inSample, false);
  const reversed = templateSelection(snapshot, ["row2", "row1"]);
  assert.deepEqual(
    [...reversed.ids],
    ["row1", "school", "degree", "row2", "other"],
  );
  assert.deepEqual(
    reversed.available.map((node) => node.id),
    ["school", "degree", "other"],
  );
  assert.equal(templateSelection(snapshot, ["photo"]).canRange, false);
  assert.equal(templateSelection(snapshot, ["picture"]).canRange, true);
  assert.equal(templateSelection(snapshot, []), null);
  assert.equal(templateSelection(snapshot, ["missing"]), null);
  assert.equal(templateSelection(snapshot, ["row1"]).inSample, true);
  assert.deepEqual({ nodes, value }, before);
});

test("共享区域索引沿用父级、部件及图片端点限制", () => {
  const nodes = fixture();
  const value = plan();
  value.repeats = [
    ["school", "degree"],
    ["name", "header"],
    ["photo", "photo"],
    ["missing", "row1"],
  ].map(([start, end]) => ({
    section: "无效范围",
    start,
    end,
    sample_start: start,
    sample_end: end,
    fields: [],
  }));
  const snapshot = templateSnapshot(nodes, value);
  assert.equal(snapshot.memberships.size, 0);
  assert.equal(
    snapshot.samples.every((sample) => sample.size === 0),
    true,
  );
  assert.deepEqual(templateSelection(snapshot, ["table"]).touched, [
    false,
    false,
    false,
    false,
  ]);
});

test("编辑方案、替换节点后重建快照，先前选区不会残留分类", () => {
  const nodes = fixture();
  const value = plan();
  const original = templateSnapshot(nodes, value);
  const changed = {
    ...value,
    repeats: value.repeats.map((region) => ({
      ...region,
      start: "row2",
      sample_start: "row2",
      sample_end: "row2",
      fields: [],
    })),
    fields: [],
    photos: [],
    remove: ["picture"],
  };
  const next = templateSnapshot(nodes, changed);
  assert.equal(templateSelection(next, ["row1"]).hasRepeat, false);
  assert.equal(templateSelection(next, ["row2"]).inSample, true);
  assert.equal(next.mappings.get("name").kind, "unresolved");
  assert.equal(next.mappings.get("photo").kind, "remove");
  assert.equal(original.mappings.get("photo").kind, "photo");
  assert.equal(templateSelection(original, ["row1"]).hasRepeat, true);
  const replaced = templateSnapshot(
    nodes.filter((node) => node.id !== "photo"),
    changed,
  );
  assert.equal(templateSelection(replaced, ["photo"]), null);
});

test("重复选择只扫描一次节点后代，不重新展开每个区域", () => {
  let ancestorReads = 0;
  const nodes = Array.from({ length: 1000 }, (_, index) => ({
    id: `node-${index}`,
    parent: "body",
    part: "word/document.xml",
    kind: "p",
    text: "合成原文",
    can_insert: false,
    get ancestors() {
      ancestorReads++;
      return [];
    },
  }));
  const value = {
    ...plan(),
    fields: [],
    photos: [],
    keep: [],
    repeats: Array.from({ length: 20 }, (_, index) => ({
      section: "合成栏目",
      start: `node-${index * 50}`,
      end: `node-${index * 50 + 49}`,
      sample_start: `node-${index * 50}`,
      sample_end: `node-${index * 50}`,
      fields: [],
    })),
  };
  const snapshot = templateSnapshot(nodes, value);
  ancestorReads = 0;
  for (let index = 0; index < 20; index++) {
    const selection = templateSelection(snapshot, [`node-${index * 50}`]);
    assert.equal(selection.inSample, true);
    assert.equal(selection.touched.filter(Boolean).length, 1);
  }
  assert.equal(ancestorReads, 20 * (nodes.length - 1));
});
