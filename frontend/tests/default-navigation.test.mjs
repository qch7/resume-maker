import assert from "node:assert/strict";
import test from "node:test";
import { builtinDefaults } from "../src/features/profile/defaults/model.ts";
import { newDocument } from "../src/features/profile/document.ts";
import {
  orderDefaultSections,
  searchDefaultFields,
} from "../src/features/profile/defaults/navigation.ts";

test("默认导航跟随编排的同级顺序，旧标识的子栏目紧跟父栏目", () => {
  const defaults = builtinDefaults();
  const document = newDocument();
  const byId = Object.fromEntries(
    document.sections.map((item) => [item.id, item]),
  );
  byId.courses.id = "legacy-courses";
  byId.skills.visible = false;
  document.sections = [
    byId.honors,
    byId.courses,
    byId.skills,
    byId.education,
    byId.projects,
  ];
  const original = structuredClone(defaults);
  assert.deepEqual(
    orderDefaultSections(defaults.sections, document).map((item) => item.id),
    ["honors", "skills", "education", "courses", "projects"],
  );
  assert.deepEqual(defaults, original);
  assert.equal(document.sections[1].id, "legacy-courses");
});

test("未采用的默认栏目保留在同级末尾，临时栏目不自动成为默认栏目", () => {
  const defaults = builtinDefaults();
  const document = newDocument();
  document.sections = document.sections
    .filter((item) => ["projects", "education"].includes(item.id))
    .reverse();
  document.sections.unshift({
    id: "custom",
    title: "临时栏目",
    kind: "text",
    parent_id: null,
    visible: true,
    entries: [],
  });
  assert.deepEqual(
    orderDefaultSections(defaults.sections, document).map((item) => item.id),
    ["projects", "education", "courses", "honors", "skills"],
  );
  assert.equal(
    orderDefaultSections(defaults.sections, null).length,
    defaults.sections.length,
  );
});

test("重名歧义不阻止设置导航，父级删除后仍能找到子栏目", () => {
  const defaults = builtinDefaults();
  const document = newDocument();
  document.sections[1].id = "old-course";
  document.sections.push({ ...document.sections[1], id: "second-course" });
  assert.equal(
    orderDefaultSections(defaults.sections, document).length,
    defaults.sections.length,
  );
  const orphaned = defaults.sections.filter((item) => item.id !== "education");
  assert.equal(
    orderDefaultSections(orphaned).filter((item) => item.id === "courses")
      .length,
    1,
  );
});

test("搜索同时匹配栏目和字段，多关键词限定所属栏目并返回准确标识", () => {
  const defaults = builtinDefaults();
  defaults.personal_fields.push({
    id: "default:github",
    label: "GitHub 地址",
    visible: false,
  });
  assert.deepEqual(searchDefaultFields(defaults, "  github  "), [
    {
      sectionId: "personal",
      fieldId: "default:github",
      title: "GitHub 地址",
      sectionTitle: "个人信息",
    },
  ]);
  assert.deepEqual(searchDefaultFields(defaults, "教育 学校"), [
    {
      sectionId: "education",
      fieldId: "title",
      title: "学校名称",
      sectionTitle: "教育背景",
    },
  ]);
  assert.equal(searchDefaultFields(defaults, "项目经历")[0].fieldId, undefined);
  assert.equal(searchDefaultFields(defaults, "电话")[0].fieldId, "phone");
  assert.deepEqual(searchDefaultFields(defaults, "   "), []);
  assert.deepEqual(searchDefaultFields(defaults, "无此栏目"), []);
});

test("同名信息项按栏目编排次序返回，改名与新增字段即时可搜索", () => {
  const defaults = builtinDefaults();
  defaults.sections.reverse();
  const results = searchDefaultFields(defaults, "标题");
  assert.deepEqual(
    results.map((item) => item.sectionId),
    ["skills", "projects", "courses"],
  );
  defaults.sections[0].fields[0].label = "技能名称";
  assert.equal(
    searchDefaultFields(defaults, "技能名称")[0].sectionId,
    "skills",
  );
  assert.equal(
    searchDefaultFields(defaults, "标题").some(
      (item) => item.sectionId === "skills",
    ),
    false,
  );
});
