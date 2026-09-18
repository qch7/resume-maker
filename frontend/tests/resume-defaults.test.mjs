import assert from "node:assert/strict";
import test from "node:test";
import {
  newDocument,
  newEntry,
  displayedPersonal,
} from "../src/features/profile/document.ts";
import {
  applyResumeDefaults,
  builtinDefaults,
  defaultHasContent,
  hasDefault,
} from "../src/features/profile/defaults/model.ts";
import { projectDefaultView } from "../src/features/profile/defaults/projects.ts";
import { addHonors } from "../src/features/honors/model.ts";
import { emptyHonor } from "../src/features/honors/fields.ts";
import { syncHonorDocument } from "../src/features/honors/sync.ts";
import { sameResumeDocument } from "../src/features/profile/comparison.ts";
import { repairDefaultDuplicates } from "../src/features/profile/defaults/sections.ts";

test("旧简历同名栏目沿用原标识和全部内容，重复应用不会再添空栏目", () => {
  const settings = builtinDefaults();
  const document = newDocument();
  const courses = document.sections.find((section) => section.id === "courses");
  courses.id = "legacy-courses";
  courses.entries = [
    { ...newEntry(), details: "数据结构、操作系统", hidden_fields: ["title"] },
  ];
  const original = structuredClone(document);
  const once = applyResumeDefaults(document, settings);
  const twice = applyResumeDefaults(once, settings, settings);
  for (const result of [once, twice]) {
    const matches = result.sections.filter(
      (section) => section.title === "主修课程",
    );
    assert.equal(matches.length, 1);
    assert.equal(matches[0].id, "legacy-courses");
    assert.equal(matches[0].parent_id, "education");
    assert.equal(matches[0].entries[0].details, "数据结构、操作系统");
    assert.deepEqual(matches[0].entries[0].hidden_fields, ["title"]);
  }
  assert.deepEqual(document, original);
  const definition = settings.sections.find(
    (section) => section.id === "courses",
  );
  assert.equal(
    defaultHasContent(once, "courses", "details", [], definition),
    true,
  );
});

test("默认父栏目使用旧标识时子栏目同步引用，手动子栏目保持层级", () => {
  const settings = builtinDefaults();
  const document = newDocument();
  document.sections[0].id = "legacy-education";
  document.sections[1].parent_id = "legacy-education";
  document.sections.push({
    id: "manual-child",
    title: "研究方向",
    kind: "text",
    parent_id: "legacy-education",
    visible: true,
    entries: [],
  });
  const result = applyResumeDefaults(document, settings);
  assert.equal(
    result.sections.filter((section) => section.title === "教育背景").length,
    1,
  );
  assert.equal(
    result.sections.find((section) => section.id === "courses").parent_id,
    "legacy-education",
  );
  assert.equal(
    result.sections.find((section) => section.id === "manual-child").parent_id,
    "legacy-education",
  );
});

test("修复已受影响草稿只移除新增空栏目，保留内容并恢复已保存父级", () => {
  const settings = builtinDefaults();
  const saved = newDocument();
  saved.sections[1].id = "legacy-courses";
  saved.sections[1].entries.push({ ...newEntry(), details: "已保存课程" });
  const broken = newDocument(settings);
  broken.sections.push({
    ...structuredClone(saved.sections[1]),
    parent_id: null,
    entries: [{ ...saved.sections[1].entries[0], details: "尚未保存的新课程" }],
  });
  broken.personal.name = "尚未保存的姓名";
  const original = structuredClone(broken);
  const repaired = repairDefaultDuplicates(broken, settings, saved);
  assert.equal(
    repaired.sections.filter((section) => section.title === "主修课程").length,
    1,
  );
  const courses = repaired.sections.find(
    (section) => section.id === "legacy-courses",
  );
  assert.equal(courses.parent_id, "education");
  assert.equal(courses.entries[0].details, "尚未保存的新课程");
  assert.equal(repaired.personal.name, "尚未保存的姓名");
  assert.deepEqual(broken, original);
  assert.equal(repairDefaultDuplicates(repaired, settings, saved), repaired);
});

test("两个都有内容的同名栏目不自动合并，空手动栏目也不自动删除", () => {
  const settings = builtinDefaults();
  const document = newDocument(settings);
  document.sections[1].entries.push({ ...newEntry(), details: "第一组课程" });
  document.sections.push({
    ...structuredClone(document.sections[1]),
    id: "legacy-courses",
    entries: [{ ...newEntry(), details: "第二组课程" }],
  });
  assert.equal(repairDefaultDuplicates(document, settings), document);
  document.sections[1].entries = [];
  document.sections[1].field_definitions = null;
  assert.equal(repairDefaultDuplicates(document, settings), document);
});

test("改名和移除默认栏目仍定位到旧简历的同名原栏目", () => {
  const previous = builtinDefaults();
  const document = newDocument();
  document.sections[1].id = "legacy-courses";
  document.sections[1].entries.push({ ...newEntry(), details: "课程内容" });
  const renamed = structuredClone(previous);
  renamed.sections[1].title = "核心课程";
  const updated = applyResumeDefaults(document, renamed, previous);
  assert.equal(
    updated.sections.find((section) => section.id === "legacy-courses").title,
    "核心课程",
  );
  assert.equal(
    updated.sections.some((section) => section.title === "主修课程"),
    false,
  );
  const deleted = structuredClone(renamed);
  deleted.sections = deleted.sections.filter(
    (section) => section.id !== "courses",
  );
  const removed = applyResumeDefaults(updated, deleted, renamed);
  assert.equal(
    removed.sections.find((section) => section.id === "legacy-courses").visible,
    false,
  );
  assert.equal(
    removed.sections.find((section) => section.id === "legacy-courses")
      .entries[0].details,
    "课程内容",
  );
});

test("保存默认设置更新当前资料，新简历只继承结构不复制值", () => {
  const settings = builtinDefaults();
  settings.personal_fields.push({
    id: "default:wechat",
    label: "微信",
    visible: true,
  });
  settings.sections[0].fields.push({
    id: "default:tutor",
    label: "导师",
    visible: false,
  });
  const first = newDocument(settings);
  first.personal.name = "张三";
  first.personal.custom_fields[0].value = "wx123";
  const education = newEntry(first.sections[0].field_definitions);
  assert.deepEqual(education.custom_fields[0], {
    id: "default:tutor",
    label: "导师",
    value: "",
    visible: false,
  });
  const second = newDocument(settings);
  assert.equal(second.personal.name, "");
  assert.equal(second.personal.custom_fields[0].value, "");
  settings.personal_fields.at(-1).label = "微信号码";
  const updated = applyResumeDefaults(first, settings);
  assert.equal(updated.personal.custom_fields[0].value, "wx123");
  assert.equal(updated.personal.custom_fields[0].label, "微信号码");
  assert.equal(first.personal.custom_fields[0].label, "微信");
});

test("删除已填写默认项须确认，隐藏值仍须确认，空项无需确认", () => {
  const settings = builtinDefaults();
  settings.personal_fields.push({
    id: "default:wechat",
    label: "微信",
    visible: false,
  });
  const document = newDocument(settings);
  assert.equal(
    defaultHasContent(document, "personal", "default:wechat"),
    false,
  );
  document.personal.custom_fields[0].value = "wx123";
  document.personal.phone = "13800000000";
  document.personal.hidden_fields.push("phone");
  assert.equal(defaultHasContent(document, "personal", "phone"), true);
  assert.equal(defaultHasContent(document, "personal", "default:wechat"), true);
  settings.personal_fields = settings.personal_fields.filter(
    (field) => !["phone", "default:wechat"].includes(field.id),
  );
  const updated = applyResumeDefaults(document, settings);
  assert.equal(updated.personal.phone, "13800000000");
  assert.equal(displayedPersonal(updated.personal).phone, "");
  assert.equal(displayedPersonal(updated.personal).custom_fields.length, 0);
  assert.equal(
    hasDefault(updated.personal.field_definitions, "default:wechat"),
    false,
  );
  assert.equal(
    hasDefault(document.personal.field_definitions, "default:wechat"),
    true,
  );
});

test("删除默认栏目保留隐藏内容，手动栏目和新默认子栏目保持独立", () => {
  const settings = builtinDefaults();
  const document = newDocument(settings);
  document.sections[0].entries.push({ ...newEntry(), title: "测试大学" });
  document.sections.push({
    id: "manual",
    title: "个人评价",
    kind: "text",
    parent_id: null,
    visible: true,
    entries: [],
  });
  settings.sections = settings.sections.filter(
    (section) => section.id !== "education",
  );
  settings.sections[0].parent_id = null;
  const updated = applyResumeDefaults(document, settings);
  assert.equal(
    updated.sections.find((section) => section.id === "education").visible,
    false,
  );
  assert.equal(
    updated.sections.find((section) => section.id === "education").entries[0]
      .title,
    "测试大学",
  );
  assert.equal(
    updated.sections.find((section) => section.id === "manual").visible,
    true,
  );
  assert.equal(defaultHasContent(document, "education"), true);
  assert.equal(defaultHasContent(document, "manual"), false);
});

test("荣誉导入和来源同步保留默认字段标签及自定义项", () => {
  const settings = builtinDefaults();
  const definitions = settings.sections.find(
    (section) => section.id === "honors",
  ).fields;
  definitions.find((field) => field.id === "honor-field:award").label =
    "获奖等次";
  definitions.push({
    id: "default:honor-note",
    label: "获奖项目",
    visible: true,
  });
  const source = {
    id: "source",
    fields: { ...emptyHonor(), name: "竞赛", award: "金奖" },
    reviewed: true,
    status: "ready",
  };
  const document = addHonors(newDocument(settings), [source]);
  const synced = syncHonorDocument(document, [source]);
  const entry = synced.sections.find((section) => section.id === "honors")
    .entries[0];
  assert.equal(
    entry.custom_fields.find((field) => field.id === "honor-field:award").label,
    "获奖等次",
  );
  assert.equal(
    entry.custom_fields.find((field) => field.id === "default:honor-note")
      .value,
    "",
  );
  assert.equal(entry.field_definitions.length, definitions.length);
});

test("项目默认项只补充表单，不改写项目原版本，容量超限不会使界面崩溃", () => {
  const original = {
    title: "项目",
    period: "",
    role: "开发",
    stack: ["Python"],
    description: "说明",
    custom_fields: [],
    highlights: [],
  };
  const definitions = builtinDefaults().sections[2].fields;
  definitions.find((field) => field.id === "role").visible = false;
  definitions.push({ id: "default:url", label: "演示链接", visible: true });
  const view = projectDefaultView(original, {}, definitions);
  assert.equal(view.value.custom_fields[0].label, "演示链接");
  assert.equal(view.visibility.fields.role, false);
  assert.deepEqual(original.custom_fields, []);
  assert.equal(
    defaultHasContent(newDocument(), "projects", "role", [original]),
    true,
  );
  assert.equal(
    defaultHasContent(newDocument(), "projects", "period", [original]),
    false,
  );
  const full = {
    ...original,
    custom_fields: Array.from({ length: 20 }, (_, index) => ({
      id: `custom-${index}`,
      label: "备注",
      value: "有值",
      visible: true,
    })),
  };
  assert.match(projectDefaultView(full, {}, definitions).error, /20/);
});

test("字段结构参与保存比较，服务端补全 null 不产生虚假未保存状态", () => {
  const original = newDocument();
  const normalized = structuredClone(original);
  normalized.personal.field_definitions = null;
  normalized.sections.forEach((section) => {
    section.field_definitions = null;
  });
  assert.equal(sameResumeDocument(original, normalized), true);
  normalized.sections[0].field_definitions = [];
  assert.equal(sameResumeDocument(original, normalized), false);
});

test("调整其他默认项不覆盖当前资料的显隐，新增荣誉采用配置的初始显隐", () => {
  const settings = builtinDefaults();
  settings.personal_fields.find((field) => field.id === "phone").visible =
    false;
  const document = newDocument(settings);
  document.personal.hidden_fields = [];
  settings.personal_fields[0].label = "本人姓名";
  assert.equal(
    applyResumeDefaults(document, settings).personal.hidden_fields.includes(
      "phone",
    ),
    false,
  );
  const definitions = settings.sections.find(
    (section) => section.id === "honors",
  ).fields;
  definitions.find((field) => field.id === "subtitle").visible = true;
  definitions.find((field) => field.id === "honor-field:award").visible = true;
  const source = {
    id: "visible",
    fields: {
      ...emptyHonor(),
      name: "奖学金",
      issuer: "学校",
      award: "一等奖",
    },
    status: "ready",
    reviewed: true,
  };
  const result = addHonors(newDocument(settings), [source]);
  const entry = result.sections.find((section) => section.id === "honors")
    .entries[0];
  assert.equal(entry.hidden_fields.includes("subtitle"), false);
  assert.equal(
    entry.custom_fields.find((field) => field.id === "honor-field:award")
      .visible,
    true,
  );
});
