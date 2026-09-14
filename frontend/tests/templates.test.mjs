import { test } from "node:test";
import assert from "node:assert/strict";
import { newDocument } from "../src/features/profile/document.ts";
import { personalComposition } from "../src/features/profile/personal.ts";
import { entryComposition } from "../src/features/profile/entry.ts";
import { personalTargets } from "../src/features/templates/mapping.ts";

test("完整模板在个人资料及栏目单独保存后继续生效", /* 验证资料编辑不会悄悄切回内置排版。 */ () => {
  const document = newDocument();
  document.sections[0].entries = [
    {
      id: "entry",
      title: "测试大学",
      subtitle: "",
      period: "",
      details: "",
      visible: true,
      hidden_fields: [],
      custom_fields: [],
    },
  ];
  const saved = {
    id: "resume",
    name: "简历",
    version: 1,
    template_id: "adaptive",
    document,
    items: [],
  };
  const draft = structuredClone(saved);
  draft.document.personal.name = "新姓名";
  assert.equal(personalComposition(draft, saved).template_id, "adaptive");
  assert.equal(
    entryComposition(draft, saved, document.sections[0].id, "entry")
      .template_id,
    "adaptive",
  );
});

test("映射选项包括当前自定义信息和所有栏目标题", /* 栏目和个人自定义资料可以参与整份模板替换。 */ () => {
  const document = newDocument();
  document.personal.custom_fields = [
    { id: "language", label: "语言", value: "中文", visible: true },
  ];
  const targets = personalTargets(document);
  assert.equal(targets["personal.name"], "姓名");
  assert.equal(targets["personal.custom:语言"], "语言");
  assert.equal(
    targets[`section-title:${document.sections[0].title}`],
    `${document.sections[0].title} · 栏目标题`,
  );
});
