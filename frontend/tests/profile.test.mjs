import { test } from "node:test";
import assert from "node:assert/strict";
import {
  newDocument,
  moveSection,
  siblings,
  removeSection,
  hasSectionContent,
  displayedPersonal,
  filledEntries,
  toggleHiddenField,
  visibleCustomFields,
} from "../src/features/profile/document.ts";
import {
  sameComposition,
  isCurrentExport,
  acceptSavedComposition,
} from "../src/features/resumes/composition.ts";

test("saving preserves newer typing and never switches away from another resume", /* 验证保存请求期间继续输入与切换方案不会被迟到的服务器响应覆盖 */ () => {
  const submitted = {
    id: "",
    name: "简历",
    template_id: null,
    items: [],
    version: 0,
    document: newDocument(),
  };
  const saved = { ...submitted, id: "saved", version: 1 };
  const typed = structuredClone(submitted);
  typed.document.personal.phone = "10000000000";
  const merged = acceptSavedComposition(typed, submitted, saved);
  assert.equal(merged.id, "saved");
  assert.equal(merged.version, 1);
  assert.equal(merged.document.personal.phone, "10000000000");
  assert.equal(sameComposition(merged, saved), false);
  assert.equal(acceptSavedComposition(submitted, submitted, saved), saved);
  const other = { ...submitted, id: "other" };
  assert.equal(acceptSavedComposition(other, submitted, saved), other);
});

test("custom information filters empty and hidden items without modifying stored values", /* 验证自定义信息按顺序参与排版；空项和隐藏项保留在草稿中 */ () => {
  const fields = [
    { id: "city", label: " 籍贯 ", value: " 杭州 ", visible: true },
    { id: "empty-name", label: " ", value: "不显示", visible: true },
    { id: "empty-value", label: "毕业时间", value: " ", visible: true },
    { id: "hidden", label: "隐藏信息", value: "保留原文", visible: false },
  ];
  const original = structuredClone(fields);
  const personal = { ...newDocument().personal, custom_fields: fields };
  assert.deepEqual(visibleCustomFields(fields), [
    { id: "city", label: "籍贯", value: "杭州", visible: true },
  ]);
  assert.equal(displayedPersonal(personal).custom_fields[0].value, "杭州");
  assert.deepEqual(fields, original);
  fields[3].visible = true;
  assert.equal(visibleCustomFields(fields)[1].value, "保留原文");
});

test("custom-only entry content participates in section visibility", /* 验证只填自定义项的资料不会丢失；隐藏整条经历时也会隐藏其扩展内容 */ () => {
  const { sections } = newDocument();
  const entry = {
    visible: true,
    hidden_fields: [],
    id: "custom-only",
    title: "主修课程",
    subtitle: "",
    period: "",
    details: "",
    custom_fields: [
      { id: "topic", label: "研究方向", value: "智能系统", visible: true },
    ],
  };
  sections[1].entries = [entry];
  assert.equal(hasSectionContent(sections[0], sections, 0), true);
  assert.equal(
    filledEntries(sections[1])[0].custom_fields[0].value,
    "智能系统",
  );
  entry.visible = false;
  assert.equal(hasSectionContent(sections[0], sections, 0), false);
  entry.visible = true;
  entry.custom_fields[0].visible = false;
  assert.equal(hasSectionContent(sections[0], sections, 0), false);
  assert.equal(entry.custom_fields[0].value, "智能系统");
});

test("personal visibility preserves values and restores them without retyping", /* 验证所有个人字段可隐藏恢复；字段原文保持不变 */ () => {
  const original = newDocument().personal;
  const fields = Object.keys(original).filter(
    /* 只操作文本字段；显隐和自定义信息是独立元数据 */ (key) =>
      typeof original[key] === "string",
  );
  for (const key of fields) original[key] = `value-${key}`;
  assert.deepEqual(displayedPersonal(original), original);
  const hidden = { ...original, hidden_fields: fields };
  const displayed = displayedPersonal(hidden);
  for (const key of fields) {
    assert.equal(displayed[key], "");
    assert.equal(hidden[key], `value-${key}`);
  }
  hidden.hidden_fields = toggleHiddenField(hidden.hidden_fields, "phone");
  assert.equal(displayedPersonal(hidden).phone, "value-phone");
  assert.equal(displayedPersonal(hidden).email, "");
});

test("course headings are deduplicated in both levels without changing stored titles", /* 验证子栏目与大栏目都只保留一层同名标题且不误删不同条目标题 */ () => {
  const section = newDocument().sections[1];
  section.entries = [
    {
      visible: true,
      hidden_fields: [],
      custom_fields: [],
      id: "course",
      title: " 主修课程 ",
      subtitle: "",
      period: "",
      details: "操作系统",
    },
    {
      visible: true,
      hidden_fields: [],
      custom_fields: [],
      id: "extra",
      title: "选修课程",
      subtitle: "",
      period: "",
      details: "计算机视觉",
    },
  ];
  for (const parent_id of ["education", null]) {
    const entries = filledEntries({ ...section, parent_id });
    assert.equal(entries[0].title, "");
    assert.equal(entries[0].details, "操作系统");
    assert.equal(entries[1].title, "选修课程");
  }
  assert.equal(section.entries[0].title, " 主修课程 ");
  assert.equal(
    filledEntries({ ...section, kind: "education" })[0].title,
    " 主修课程 ",
  );
});

test("hidden entry fields and rows never leave orphan headings", /* 验证条目与字段显隐可组合；全部隐藏时连同空父子栏目标题省略 */ () => {
  const { sections } = newDocument();
  const course = {
    visible: true,
    custom_fields: [],
    id: "course",
    title: "主修课程",
    subtitle: "",
    period: "",
    details: "操作系统",
    hidden_fields: ["details"],
  };
  const extra = {
    hidden_fields: [],
    custom_fields: [],
    id: "extra",
    title: "选修课程",
    subtitle: "",
    period: "",
    details: "计算机视觉",
    visible: false,
  };
  sections[1].entries = [course, extra];
  assert.deepEqual(filledEntries(sections[1]), []);
  assert.equal(hasSectionContent(sections[0], sections, 0), false);
  course.hidden_fields = toggleHiddenField(course.hidden_fields, "details");
  assert.equal(hasSectionContent(sections[0], sections, 0), true);
  assert.equal(filledEntries(sections[1]).length, 1);
  assert.equal(extra.details, "计算机视觉");
  extra.visible = true;
  assert.equal(filledEntries(sections[1]).length, 2);
});

test("reordering a major section carries its children without changing their content", /* 验证大栏目排序与子栏目归属独立并保持原数据不变 */ () => {
  const original = newDocument();
  const sections = moveSection(original.sections, null, 0, 2);
  assert.deepEqual(
    siblings(sections).map(/* 取出大栏目顺序 */ (item) => item.id),
    ["projects", "honors", "education", "skills"],
  );
  assert.equal(siblings(sections, "education")[0].id, "courses");
  assert.equal(original.sections[0].id, "education");
  assert.equal(moveSection(sections, null, -1, 1), sections);
});

test("removing a parent keeps child data and the projects section can only be hidden", /* 验证父栏目删除不连带丢失课程资料；项目区不能被删除 */ () => {
  const original = newDocument().sections;
  original[1].entries.push({
    visible: true,
    hidden_fields: [],
    custom_fields: [],
    id: "entry",
    title: "",
    subtitle: "",
    period: "",
    details: "操作系统",
  });
  const sections = removeSection(original, "education");
  const course = sections.find(
    /* 定位保留下来的课程栏目 */ (section) => section.id === "courses",
  );
  assert.equal(course.parent_id, null);
  assert.equal(course.entries[0].details, "操作系统");
  assert.equal(removeSection(sections, "projects").length, sections.length);
});

test("project sections include child content even without selected projects", /* 所有大栏目都允许子栏目；项目区空白、显隐和排序仍遵循同样规则 */ () => {
  const { sections } = newDocument();
  const project = sections[2];
  const child = sections[1];
  child.parent_id = project.id;
  assert.equal(hasSectionContent(project, sections, 0), false);
  child.entries.push({
    visible: true,
    hidden_fields: [],
    custom_fields: [],
    id: "note",
    title: "",
    subtitle: "",
    period: "",
    details: "补充成果",
  });
  assert.equal(hasSectionContent(project, sections, 0), true);
  assert.equal(hasSectionContent(project, sections, 1), true);
  const moved = moveSection(sections, null, 1, 0);
  assert.equal(siblings(moved)[0].id, "projects");
  assert.equal(siblings(moved, "projects")[0], child);
  child.visible = false;
  assert.equal(hasSectionContent(project, sections, 0), false);
  assert.equal(hasSectionContent(project, sections, 1), true);
  project.visible = false;
  child.visible = true;
  assert.equal(hasSectionContent(project, sections, 1), false);
});

test("hidden and empty fields do not leave orphan headings in the preview", /* 验证空白、子栏目内容与父级显隐共同决定成品内容 */ () => {
  const { sections } = newDocument();
  assert.equal(hasSectionContent(sections[0], sections, 0), false);
  sections[1].entries.push({
    visible: true,
    hidden_fields: [],
    custom_fields: [],
    id: "entry",
    title: "",
    subtitle: "",
    period: "",
    details: "操作系统",
  });
  assert.equal(hasSectionContent(sections[0], sections, 0), true);
  sections[0].visible = false;
  assert.equal(hasSectionContent(sections[0], sections, 0), false);
});

test("profile and hierarchy edits invalidate saved state and the previous export", /* 验证只改资料或栏目顺序也必须重新保存与导出；旧方案仍可比较 */ () => {
  const base = {
    id: "resume",
    name: "简历",
    template_id: null,
    items: [],
    version: 1,
    document: newDocument(),
  };
  const edited = structuredClone(base);
  edited.document.personal.name = "新姓名";
  assert.equal(sameComposition(base, edited), false);
  assert.equal(
    isCurrentExport({ resume_id: base.id, manifest: { resume: base } }, edited),
    false,
  );
  const reordered = {
    ...base,
    document: {
      ...base.document,
      sections: moveSection(base.document.sections, null, 0, 1),
    },
  };
  assert.equal(sameComposition(base, reordered), false);
  assert.equal(
    sameComposition(
      { ...base, document: undefined },
      { ...base, document: null },
    ),
    true,
  );
  assert.equal(newDocument().personal.name, "");
});
