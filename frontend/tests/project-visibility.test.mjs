import { test } from "node:test";
import assert from "node:assert/strict";
import {
  experienceContent,
  fieldVisible,
} from "../src/features/experiences/visibility.ts";
import { buildLivePreview } from "../src/features/resumes/livePreview.ts";
import { sameResumeDocument } from "../src/features/profile/comparison.ts";
import { newDocument } from "../src/features/profile/document.ts";
import { toggleHighlightSelection } from "../src/features/resumes/composition.ts";
import { projectBodyOrder } from "../src/features/experiences/bodyOrder.ts";
import { revisionChanges } from "../src/features/experiences/history.ts";

/** 创建带隐藏默认值的旧项目版本；测试新覆盖可同时隐藏和恢复 */
function fixture() {
  const content = {
    title: "项目",
    period: "2026",
    role: "开发",
    stack: ["Python"],
    description: "正文",
    hidden_fields: ["stack"],
    custom_fields: [
      { id: "link", label: "链接", value: "example.test", visible: false },
    ],
    highlights: [
      { id: "a", title: "亮点甲", text: "甲正文", evidence: [] },
      { id: "b", title: "亮点乙", text: "乙正文", evidence: [] },
    ],
  };
  const revision = { id: "r1", project_id: "project", content };
  const draft = {
    document: newDocument(),
    items: [
      { project_id: "project", revision_id: "r1", highlight_ids: ["a", "b"] },
    ],
  };
  return { content, revision, draft };
}

test("项目显隐与亮点选择只改变简历，允许直接保存同一版本", /* 验证无需内容草稿即可隐藏和恢复；保留亮点原始顺序 */ () => {
  const { content, revision, draft } = fixture();
  const before = structuredClone({ content, draft });
  const next = structuredClone(draft);
  next.document.project_visibility = {
    project: {
      order: ["custom:link", "highlights", "role", "description", "stack"],
      fields: { role: false, stack: true },
      custom_fields: { link: true },
    },
  };
  next.items[0].highlight_ids = toggleHighlightSelection(
    content.highlights,
    next.items[0].highlight_ids,
    "a",
  );
  assert.deepEqual(next.items[0].highlight_ids, ["b"]);
  assert.equal(
    buildLivePreview(next, { r1: revision }, {}, "project", "r1").changed,
    false,
  );
  assert.equal(sameResumeDocument(draft.document, next.document), false);
  assert.equal(
    fieldVisible(content, next.document.project_visibility.project, "stack"),
    true,
  );
  assert.equal(
    fieldVisible(content, next.document.project_visibility.project, "role"),
    false,
  );
  next.items[0].highlight_ids = toggleHighlightSelection(
    content.highlights,
    next.items[0].highlight_ids,
    "a",
  );
  assert.deepEqual(next.items[0].highlight_ids, ["a", "b"]);
  assert.deepEqual({ content, draft }, before);
});

test("旧版简历顺序仍可读取，标题时间固定，新字段自动追加", /* 版本切换忽略缺失项但保留其存储位置；旧设置不自动改变经历 */ () => {
  const { content, revision, draft } = fixture();
  const settings = {
    order: [
      "custom:missing",
      "highlights",
      "custom:link",
      "highlights",
      "title",
      "period",
    ],
  };
  const before = structuredClone(settings);
  assert.deepEqual(projectBodyOrder(content, settings), [
    "highlights",
    "custom:link",
    "role",
    "stack",
    "description",
  ]);
  const added = {
    ...content,
    custom_fields: [
      ...content.custom_fields,
      { id: "new", label: "新增", value: "文本", visible: true },
    ],
  };
  assert.equal(projectBodyOrder(added, settings).at(-1), "custom:new");
  assert.equal(
    projectBodyOrder(
      {
        ...content,
        custom_fields: [{ ...content.custom_fields[0], id: "missing" }],
      },
      settings,
    )[0],
    "custom:missing",
  );
  assert.deepEqual(settings, before);
  const next = structuredClone(draft);
  next.document.project_visibility = {
    project: { order: ["highlights", "role"] },
  };
  assert.equal(sameResumeDocument(draft.document, next.document), false);
  assert.equal(
    buildLivePreview(next, { r1: revision }, {}, "project", "r1").changed,
    false,
  );
});

test("基本信息排序进入版本，提交前阻止导出并记录历史差异", /* 版本排序优先于简历顺序 */ () => {
  const { content, revision, draft } = fixture();
  const settings = { order: ["stack", "role"] };
  const order = ["custom:link", "highlights", "description", "role", "stack"];
  const working = { ...content, body_order: order };
  assert.deepEqual(projectBodyOrder(working, settings), order);
  assert.equal(
    buildLivePreview(draft, { r1: revision }, { r1: working }, "project", "r1")
      .changed,
    true,
  );
  assert.deepEqual(
    revisionChanges({ ...revision, content: working }, revision),
    ["基本信息顺序"],
  );
  assert.equal(
    experienceContent(content),
    experienceContent({ ...content, body_order: null }),
  );
  assert.deepEqual(
    content.highlights.map(/* 移动占位行不改组内顺序 */ (point) => point.id),
    ["a", "b"],
  );
});

test("显隐不改变版本内容判断", () => {
  const { content } = fixture();
  const visible = {
    ...content,
    hidden_fields: ["role"],
    custom_fields: [{ ...content.custom_fields[0], visible: true }],
  };
  assert.equal(experienceContent(visible), experienceContent(content));
  for (const changed of [
    { ...visible, role: "新角色" },
    { ...visible, custom_fields: [] },
    {
      ...visible,
      custom_fields: [
        ...visible.custom_fields,
        { id: "new", label: "规模", value: "三人", visible: false },
      ],
    },
  ]) {
    assert.notEqual(experienceContent(changed), experienceContent(content));
  }
});

test("缺省设置兼容旧版，当前文字变更仍会阻止直接导出", /* 避免仅补默认字段误报未提交；也避免忽略真正的正文输入 */ () => {
  const { content, revision, draft } = fixture();
  const { hidden_fields: _hidden, custom_fields: _custom, ...legacy } = content;
  assert.equal(
    experienceContent(legacy),
    experienceContent({ ...legacy, hidden_fields: [], custom_fields: [] }),
  );
  const working = { ...content, description: "尚未提交" };
  assert.equal(
    buildLivePreview(draft, { r1: revision }, { r1: working }, "project", "r1")
      .changed,
    true,
  );
  assert.equal(
    sameResumeDocument(draft.document, {
      ...draft.document,
      project_visibility: {},
    }),
    true,
  );
});
