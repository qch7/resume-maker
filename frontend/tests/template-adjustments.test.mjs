import { test } from "node:test";
import assert from "node:assert/strict";
import { adjustmentChoices } from "../src/features/templates/adjustments.ts";

/** 构造正文中的真实位置以免测试依赖用户模板 */
function node(id, text = "", kind = "p") {
  return {
    id,
    text,
    kind,
    parent: "body",
    part: "word/document.xml",
    ancestors: [],
    can_insert: !text,
  };
}

/** 建立最小方案；按场景补充填写用途 */
function plan(overrides = {}) {
  return {
    fields: [],
    repeats: [],
    photos: [],
    keep: [],
    remove: [],
    summary: "",
    warnings: [],
    ...overrides,
  };
}

test("大量空段落不会挤入常用修正入口，同段资料合并而独立位置仍可选", /* 模拟姓名和年龄共用一段、电话有两个位置的模板 */ () => {
  const nodes = [
    ...Array.from(
      { length: 1000 },
      /* 空位不应该要求逐一处理 */ (_, index) => node(`blank-${index}`),
    ),
    node("name", "示例 21岁"),
    node("phone", "123"),
    node("phone-copy", "123"),
    node("title", "教育经历"),
  ];
  const groups = adjustmentChoices(
    nodes,
    plan({
      fields: [
        { node: "name", target: "personal.name" },
        { node: "name", target: "personal.age" },
        { node: "phone", target: "personal.phone" },
        { node: "phone-copy", target: "personal.phone" },
        { node: "missing", target: "personal.email" },
      ],
      keep: ["title"],
    }),
  );
  assert.equal(groups.length, 1);
  assert.deepEqual(
    groups[0].choices.map(/* 检查所有可选的真实位置 */ (choice) => choice.id),
    ["name", "phone", "phone-copy"],
  );
  assert.equal(groups[0].choices[0].label, "姓名 / 年龄");
});

test("重复栏目、照片、待确认文字和已映射空位都保留修正入口", /* 常用列表精简时不能漏掉需要修复的内容 */ () => {
  const nodes = [
    node("project", "示例项目"),
    node("photo", "", "image"),
    node("unknown", "待确认的技能"),
    node("blank"),
    node("remove", "旧例子"),
  ];
  const groups = adjustmentChoices(
    nodes,
    plan({
      fields: [{ node: "blank", target: "personal.email" }],
      repeats: [
        {
          section: "projects",
          start: "project",
          end: "project",
          sample_start: "project",
          sample_end: "project",
          fields: [{ node: "project", target: "title" }],
        },
      ],
      photos: ["photo"],
      remove: ["remove"],
    }),
  );
  assert.deepEqual(
    groups.map(/* 分类名称应使用用户熟悉的用途 */ (group) => group.label),
    ["个人资料与标题", "项目经历", "照片", "待确认内容"],
  );
  assert.deepEqual(
    groups.flatMap(
      /* 检查每类内容都有可用的选择入口 */ (group) =>
        group.choices.map(/* 读取真实节点 */ (choice) => choice.id),
    ),
    ["blank", "project", "photo", "unknown"],
  );
});
