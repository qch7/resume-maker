import { test } from "node:test";
import assert from "node:assert/strict";
import { newDocument } from "../src/features/profile/document.ts";
import { personalComposition } from "../src/features/profile/personal.ts";
import { samePersonalInfo } from "../src/features/profile/comparison.ts";
import {
  acceptSavedComposition,
  sameComposition,
} from "../src/features/resumes/composition.ts";

test("saving personal information leaves other pending sections and project selections unpublished", /* 基本信息保存后仍保留其他栏目和项目引用草稿 */ () => {
  const saved = {
    id: "resume",
    name: "已保存方案",
    template_id: null,
    version: 2,
    items: [],
    document: newDocument(),
  };
  saved.document.personal.name = "原姓名";
  saved.document.sections[0].entries = [
    {
      visible: true,
      hidden_fields: [],
      custom_fields: [],
      id: "school",
      title: "已保存学校",
      subtitle: "",
      period: "",
      details: "",
    },
  ];
  const draft = structuredClone(saved);
  draft.name = "未保存的方案名";
  draft.document.personal.name = "新姓名";
  draft.document.personal.custom_fields = [
    { id: "city", label: "籍贯", value: "杭州", visible: true },
  ];
  draft.document.sections[0].entries[0].custom_fields = [
    { id: "topic", label: "研究方向", value: "人工智能", visible: true },
  ];
  draft.document.sections[0].entries[0].title = "未保存的学校";
  draft.items = [
    {
      project_id: "project",
      revision_id: "revision",
      highlight_ids: ["unpublished"],
    },
  ];
  const submitted = personalComposition(draft, saved);
  assert.equal(submitted.name, "已保存方案");
  assert.equal(submitted.document.personal.name, "新姓名");
  assert.equal(submitted.document.personal.custom_fields[0].value, "杭州");
  assert.deepEqual(submitted.document.sections[0].entries[0].custom_fields, []);
  assert.equal(submitted.document.sections[0].entries[0].title, "已保存学校");
  assert.deepEqual(submitted.items, []);
  assert.equal(saved.document.personal.name, "原姓名");
  const response = { ...submitted, version: 3 };
  const merged = acceptSavedComposition(draft, submitted, response);
  assert.equal(merged.version, 3);
  assert.equal(merged.document.sections[0].entries[0].title, "未保存的学校");
  assert.equal(
    merged.document.sections[0].entries[0].custom_fields[0].value,
    "人工智能",
  );
  assert.deepEqual(merged.items, draft.items);
  assert.equal(sameComposition(merged, response), false);
});

test("a new resume can save personal data while unfinished sections remain a draft", /* 验证新方案建立数据库身份后，其他未完成资料不会丢失或意外发布 */ () => {
  const draft = {
    id: "",
    name: "新方案",
    template_id: null,
    items: [],
    version: 0,
    document: newDocument(),
  };
  draft.document.personal.phone = "10000000000";
  draft.document.sections[0].title = "未保存栏目名";
  const submitted = personalComposition(draft);
  assert.equal(submitted.document.personal.phone, "10000000000");
  assert.equal(submitted.document.sections[0].title, "教育背景");
  const merged = acceptSavedComposition(draft, submitted, {
    ...submitted,
    id: "created",
    version: 1,
  });
  assert.equal(merged.id, "created");
  assert.equal(merged.document.sections[0].title, "未保存栏目名");
  assert.throws(
    /* 已删除方案不能被基本信息保存偷偷重建 */ () =>
      personalComposition({ ...draft, id: "deleted" }),
    /已不存在/,
  );
});

test("personal save responses never erase newer typing or switch resumes", /* 保存响应只结束对应输入的编辑状态 */ () => {
  const submitted = {
    id: "one",
    name: "简历",
    template_id: null,
    version: 1,
    items: [],
    document: newDocument(),
  };
  submitted.document.personal.name = "请求发出时的姓名";
  const response = {
    ...submitted,
    version: 2,
    document: {
      ...submitted.document,
      personal: {
        ...submitted.document.personal,
        hidden_fields: [],
        custom_fields: [],
      },
    },
  };
  const newer = structuredClone(submitted);
  newer.document.personal.name = "之后输入的姓名";
  const merged = acceptSavedComposition(newer, submitted, response);
  assert.equal(merged.version, 2);
  assert.equal(merged.document.personal.name, "之后输入的姓名");
  assert.equal(
    samePersonalInfo(merged.document.personal, response.document.personal),
    false,
  );
  const other = { ...newer, id: "other" };
  assert.equal(acceptSavedComposition(other, submitted, response), other);
});

test("object property order and visibility selection order do not keep a full save dirty", /* 属性顺序和显隐勾选顺序不影响保存状态，内容和可见性变化仍可识别 */ () => {
  const draft = {
    id: "template",
    name: "简历",
    template_id: null,
    version: 1,
    items: [],
    document: newDocument(),
  };
  draft.document.personal.name = "测试同学";
  draft.document.personal.hidden_fields = ["phone", "age"];
  draft.document.sections[0].entries = [
    {
      visible: true,
      hidden_fields: [],
      custom_fields: [],
      id: "school",
      title: "大学",
      subtitle: "本科",
      period: "2024",
      details: "",
    },
  ];
  const normalized = structuredClone(draft);
  normalized.version = 2;
  normalized.document.personal = {
    custom_fields: [],
    ...normalized.document.personal,
    hidden_fields: ["age", "phone"],
  };
  normalized.document.sections[0].entries[0] = {
    custom_fields: [],
    hidden_fields: [],
    visible: true,
    ...normalized.document.sections[0].entries[0],
  };
  assert.equal(
    samePersonalInfo(draft.document.personal, normalized.document.personal),
    true,
  );
  assert.equal(sameComposition(draft, normalized), true);
  assert.equal(
    acceptSavedComposition(draft, normalized, normalized),
    normalized,
  );
  normalized.document.sections[0].entries[0].visible = false;
  assert.equal(sameComposition(draft, normalized), false);
  normalized.document.personal.phone = "新电话";
  assert.equal(
    samePersonalInfo(draft.document.personal, normalized.document.personal),
    false,
  );
});

test("personal saving keeps the original version for conflict detection and handles template-based resumes", /* 验证轮询期间的新版本不能绕过乐观锁，模板方案仍可切换为完整简历 */ () => {
  const draft = {
    id: "resume",
    name: "旧方案",
    template_id: null,
    items: [],
    version: 2,
    document: newDocument(),
  };
  draft.document.personal.name = "测试同学";
  const saved = {
    ...draft,
    version: 3,
    template_id: "template",
    document: null,
  };
  const submitted = personalComposition(draft, saved);
  assert.equal(submitted.version, 2);
  assert.equal(submitted.template_id, null);
  assert.equal(submitted.document.personal.name, "测试同学");
  assert.equal(submitted.document.sections[0].title, "教育背景");
});
