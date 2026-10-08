import { test } from "node:test";
import assert from "node:assert/strict";
import { recoverResume } from "../src/shared/resume/recovery.ts";
import { newDocument } from "../src/shared/resume/document.ts";

test("missing project preserves unrelated personal data, sections and fixed references", /* 只隔离已删除项目，完整原稿仍可作为恢复副本 */ () => {
  const draft = {
    id: "resume",
    version: 3,
    name: "我的草稿",
    template_id: "unavailable-plugin",
    document: newDocument(),
    items: [
      { project_id: "deleted", revision_id: "r1", highlight_ids: ["h1"] },
      { project_id: "valid", revision_id: "r2", highlight_ids: ["h2"] },
    ],
  };
  draft.document.personal.name = "未保存姓名";
  draft.document.personal.email = "draft@example.test";
  const before = structuredClone(draft);
  const result = recoverResume(draft, {
    projects: [{ id: "valid" }],
    resumes: [{ id: "resume" }],
    templates: [],
  });
  assert.equal(result.changed, true);
  assert.deepEqual(result.draft.document, before.document);
  assert.deepEqual(result.draft.items, [draft.items[1]]);
  assert.equal(result.draft.template_id, "unavailable-plugin");
  assert.equal(result.draft.version, 3);
  assert.deepEqual(draft, before);
});

test("deleted resume recovers as unsaved with original content", /* 方案不存在时恢复新草稿，不改选第一份方案覆盖原输入 */ () => {
  const draft = {
    id: "deleted",
    version: 5,
    name: "待恢复",
    template_id: null,
    document: newDocument(),
    items: [],
  };
  const result = recoverResume(draft, {
    projects: [],
    resumes: [{ id: "other" }],
    templates: [],
  });
  assert.equal(result.draft.id, "");
  assert.equal(result.draft.version, 0);
  assert.equal(result.draft.name, draft.name);
  assert.equal(result.draft.document, draft.document);
});
