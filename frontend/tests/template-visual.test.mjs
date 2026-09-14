import { test } from "node:test";
import assert from "node:assert/strict";
import {
  siblingRange,
  descendants,
  mappingIndex,
  highlightedText,
  clearNodes,
  repeatNodes,
} from "../src/features/templates/visual.ts";

/** 构造包含多个单元格、图片和页眉的脱敏模板结构。 */
function fixture() {
  /** 为每个位置明确记录其直接容器与可见祖先。 */
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

/** 生成包含一条教育样本和两行原文的模板映射。 */
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

test("同级范围按原文排序，跨单元格、跨部件和图片范围不能拼接", /* 用户反向点击仍选取完整闭区间。 */ () => {
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

test("选择表格行或图片容器时包含全部后代，单条样本不包含第二条示例", /* 层级选择不能漏掉单元格或内嵌图片。 */ () => {
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

test("字段、重复示例、照片和删除容器呈现不同用途", /* 删除优先级必须覆盖内部字段与照片，容器不误报待处理。 */ () => {
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

test("精确引文高亮尊重出现次数和标签，错误引文不制造虚假字段", /* 同段相同值只高亮指定的一次。 */ () => {
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

test("重新分类撤销覆盖当前节点的删除标记，保留其他区域和重复方案", /* 手工调整照片不误删姓名、页眉或教育映射。 */ () => {
  const value = { ...plan(), remove: ["picture", "other"] };
  const cleared = clearNodes(value, fixture(), ["photo"]);
  assert.deepEqual(cleared.photos, []);
  assert.deepEqual(cleared.remove, ["other"]);
  assert.deepEqual(cleared.keep, ["header"]);
  assert.deepEqual(cleared.fields, value.fields);
  assert.deepEqual(cleared.repeats, value.repeats);
  assert.deepEqual(value.photos, ["photo"]);
});
