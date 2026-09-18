import { acceptSavedComposition } from "../src/features/resumes/composition.ts";
import { test } from "node:test";
import assert from "node:assert/strict";
import { newDocument } from "../src/features/profile/document.ts";
import { sameSectionEntry } from "../src/features/profile/comparison.ts";
import {
  entryComposition,
  findEntry,
  replaceEntry,
} from "../src/features/profile/entry.ts";

test("modal entry saves apply only on success and retain unrelated drafts", /* 模态表单不提前污染草稿，保存时只提交本条，保留其他输入。 */ () => {
  const saved = baseline();
  const draft = structuredClone(saved);
  draft.document.personal.name = "未保存姓名";
  findEntry(draft.document, "education", "two").title = "另一条草稿";
  const before = structuredClone(draft);
  const edited = {
    ...findEntry(draft.document, "education", "one"),
    title: "表单名称",
    hidden_fields: ["period"],
  };
  const pending = replaceEntry(draft, "education", edited);
  const submitted = entryComposition(pending, saved, "education", edited.id);
  assert.deepEqual(draft, before);
  assert.equal(submitted.document.personal.name, "已保存姓名");
  assert.equal(findEntry(submitted.document, "education", "two").title, "two");
  const accepted = acceptSavedComposition(pending, submitted, {
    ...submitted,
    version: 3,
  });
  assert.equal(accepted.document.personal.name, "未保存姓名");
  assert.equal(
    findEntry(accepted.document, "education", "two").title,
    "另一条草稿",
  );
  assert.deepEqual(findEntry(accepted.document, "education", "one"), edited);
  assert.equal(accepted.version, 3);
});

/** 使用独立测试资料覆盖多条经历及字段显隐。 */
function baseline() {
  const document = newDocument();
  document.personal.name = "已保存姓名";
  document.sections[0].entries = ["one", "two"].map(
    /* 两条资料具有不同的稳定身份。 */ (id) => ({
      visible: true,
      hidden_fields: [],
      custom_fields: [],
      id,
      title: id,
      subtitle: "",
      period: "",
      details: "",
    }),
  );
  return {
    id: "resume",
    name: "已保存方案",
    template_id: null,
    version: 2,
    items: [],
    document,
  };
}

test("entry saves isolate other drafts without losing pending changes", /* 保存一条时不提交其他经历、姓名、编排与项目引用。 */ () => {
  const saved = baseline();
  const draft = structuredClone(saved);
  draft.name = "方案草稿";
  draft.document.personal.name = "姓名草稿";
  draft.document.sections[0].title = "栏目草稿";
  draft.document.sections[0].entries.reverse();
  findEntry(draft.document, "education", "one").title = "本次学校";
  findEntry(draft.document, "education", "one").hidden_fields = ["period"];
  findEntry(draft.document, "education", "two").title = "另一条草稿";
  draft.items = [
    { project_id: "pending", revision_id: "pending", highlight_ids: [] },
  ];
  const submitted = entryComposition(draft, saved, "education", "one");
  assert.equal(submitted.name, saved.name);
  assert.deepEqual(submitted.document.personal, saved.document.personal);
  assert.deepEqual(submitted.items, []);
  assert.equal(submitted.document.sections[0].title, "教育背景");
  assert.deepEqual(
    submitted.document.sections[0].entries.map(
      /* 确认未提交草稿排序。 */ (entry) => entry.title,
    ),
    ["本次学校", "two"],
  );
  const response = structuredClone(submitted);
  response.version = 3;
  Object.assign(findEntry(response.document, "education", "one"), {
    visible: true,
    custom_fields: [],
  });
  const merged = acceptSavedComposition(draft, submitted, response);
  assert.equal(merged.version, 3);
  assert.deepEqual(merged.items, draft.items);
  assert.equal(merged.document.personal.name, "姓名草稿");
  assert.equal(merged.document.sections[0].title, "栏目草稿");
  assert.deepEqual(
    merged.document.sections[0].entries.map(
      /* 草稿排序继续保留。 */ (entry) => entry.id,
    ),
    ["two", "one"],
  );
  assert.equal(
    findEntry(merged.document, "education", "two").title,
    "另一条草稿",
  );
  assert.deepEqual(
    findEntry(merged.document, "education", "one"),
    findEntry(response.document, "education", "one"),
  );
  assert.equal(
    sameSectionEntry(
      findEntry(draft.document, "education", "one"),
      findEntry(response.document, "education", "one"),
    ),
    true,
  );
});

test("entry responses preserve later typing, removals and selected resumes", /* 迟到保存响应不会覆盖新输入、恢复已删除条目或切回旧方案。 */ () => {
  const submitted = baseline();
  const response = { ...submitted, version: 3 };
  const current = structuredClone(submitted);
  current.document.sections[0].entries[0].details = "请求后的输入";
  const merged = acceptSavedComposition(current, submitted, response);
  assert.equal(merged.version, 3);
  assert.equal(merged.document.sections[0].entries[0].details, "请求后的输入");
  current.document.sections[0].entries.shift();
  assert.equal(
    findEntry(
      acceptSavedComposition(current, submitted, response).document,
      "education",
      "one",
    ),
    undefined,
  );
  const other = { ...current, id: "other" };
  assert.equal(acceptSavedComposition(other, submitted, response), other);
});

test("new child entries save only their necessary structure and work with new or template-based resumes", /* 新栏目只补齐父级结构，空条目也能保存为只读记录。 */ () => {
  const saved = baseline();
  const draft = structuredClone(saved);
  const entry = {
    visible: true,
    hidden_fields: [],
    custom_fields: [],
    id: "new",
    title: "",
    subtitle: "",
    period: "",
    details: "",
  };
  draft.document.sections.push(
    {
      id: "parent",
      title: "自定义大栏目",
      kind: "text",
      parent_id: null,
      visible: true,
      entries: [{ ...entry, id: "pending", details: "父栏目草稿" }],
    },
    {
      id: "child",
      title: "自定义子栏目",
      kind: "text",
      parent_id: "parent",
      visible: true,
      entries: [entry, { ...entry, id: "other" }],
    },
  );
  const submitted = entryComposition(draft, saved, "child", "new");
  assert.deepEqual(submitted.document.sections.at(-2).entries, []);
  assert.deepEqual(submitted.document.sections.at(-1).entries, [entry]);
  assert.equal(
    sameSectionEntry(entry, {
      ...entry,
      visible: true,
      hidden_fields: [],
      custom_fields: [],
    }),
    true,
  );
  assert.equal(sameSectionEntry(entry, undefined), false);
  const initial = entryComposition(
    { ...draft, id: "", version: 0 },
    undefined,
    "child",
    "new",
  );
  assert.equal(initial.document.personal.name, "");
  assert.deepEqual(initial.items, []);
  const merged = acceptSavedComposition({ ...draft, id: "" }, initial, {
    ...initial,
    id: "created",
    version: 1,
  });
  assert.equal(merged.id, "created");
  assert.equal(
    merged.document.sections.at(-2).entries[0].details,
    "父栏目草稿",
  );
  const template = entryComposition(
    draft,
    { ...saved, version: 5, template_id: "template", document: null },
    "education",
    "one",
  );
  assert.equal(template.version, 2);
  assert.equal(template.template_id, null);
  assert.throws(
    /* 已删除方案不能被局部保存重建。 */ () =>
      entryComposition(draft, undefined, "education", "one"),
    /已不存在/,
  );
});

test("entries in new project child sections save without publishing other drafts", /* 项目大栏目新增子栏目后，单条资料也能保存并保留原项目引用。 */ () => {
  const saved = baseline();
  const draft = structuredClone(saved);
  draft.document.personal.name = "未保存姓名";
  const entry = {
    visible: true,
    hidden_fields: [],
    custom_fields: [],
    id: "note",
    title: "",
    subtitle: "",
    period: "",
    details: "项目补充成果",
  };
  draft.document.sections.push({
    id: "results",
    title: "项目成果",
    kind: "text",
    parent_id: "projects",
    visible: true,
    entries: [entry],
  });
  const submitted = entryComposition(draft, saved, "results", "note");
  assert.deepEqual(findEntry(submitted.document, "results", "note"), entry);
  assert.equal(submitted.document.sections.at(-1).parent_id, "projects");
  assert.equal(submitted.document.personal.name, saved.document.personal.name);
  assert.deepEqual(submitted.items, saved.items);
});
