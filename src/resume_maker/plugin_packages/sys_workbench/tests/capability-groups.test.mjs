import assert from "node:assert/strict";
import test from "node:test";
import { capabilityGroups } from "../client/features/plugins/capabilityGroups.ts";

const plugins = [
  {
    id: "ocr",
    title: "文字识别",
    required: false,
    capability_groups: [{ id: "ocr", title: "OCR 识别" }],
  },
  {
    id: "recognition",
    title: "荣誉识别",
    required: false,
    capability_groups: [
      { id: "ocr", title: "OCR 识别" },
      { id: "honors", title: "荣誉" },
    ],
  },
  {
    id: "logs",
    title: "日志基础",
    required: true,
    capability_groups: [{ id: "logs", title: "日志" }],
  },
  {
    id: "log-ui",
    title: "日志界面",
    required: false,
    capability_groups: [{ id: "logs", title: "日志" }],
  },
  {
    id: "task",
    title: "任务日志",
    required: false,
    scope: "task",
    capability_groups: [{ id: "logs", title: "日志" }],
  },
  { id: "unknown", title: "旧版扩展", required: false },
];

test("分类支持跨领域插件，旧清单继续出现在未分类中", () => {
  const groups = capabilityGroups(plugins, [], "");
  assert.deepEqual(
    groups.find((item) => item.id === "ocr").members.map((item) => item.id),
    ["ocr", "recognition"],
  );
  assert.equal(
    groups.find((item) => item.id === "honors").members[0].id,
    "recognition",
  );
  assert.equal(
    groups.find((item) => item.id === "uncategorized").items[0].id,
    "unknown",
  );
});

test("领域名称可搜索，搜索单个插件仍保留整组开关范围", () => {
  const [group] = capabilityGroups(plugins, ["recognition"], "文字识别");
  assert.equal(group.items.length, 1);
  assert.equal(group.members.length, 2);
  assert.equal(group.selection.checked, "mixed");
  assert.equal(group.selection.total, 2);
  assert.equal(capabilityGroups(plugins, [], "OCR")[0].items.length, 2);
});

test("必需插件和任务实例不进入领域开关计数", () => {
  const group = capabilityGroups(plugins, ["logs", "log-ui"], "日志")[0];
  assert.equal(group.selection.checked, true);
  assert.equal(group.selection.count, 1);
  assert.equal(group.selection.total, 1);
  assert.equal(
    capabilityGroups(plugins, ["logs"], "日志")[0].selection.checked,
    false,
  );
});
