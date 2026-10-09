import { test } from "node:test";
import assert from "node:assert/strict";
import { buildLivePreview } from "../src/features/resumes/livePreview.ts";
import {
  orderCompositionHighlights,
  toggleHighlightSelection,
} from "../src/features/resumes/composition.ts";

/** 构造已固定的简历和三个可独立编辑的经历版本 */
function fixture() {
  const content = {
    title: "Project",
    period: "2026",
    role: "Engineer",
    stack: ["Python"],
    description: "Original description",
    highlights: [
      { id: "a", title: "First", text: "First text", evidence: [] },
      { id: "b", title: "Second", text: "Second text", evidence: [] },
      { id: "c", title: "Third", text: "Third text", evidence: [] },
    ],
  };
  const revisions = {
    old: { id: "old", project_id: "project", number: 1, content },
    newer: {
      id: "newer",
      project_id: "project",
      number: 2,
      content: { ...content, title: "Newer project" },
    },
    other: {
      id: "other",
      project_id: "other",
      number: 1,
      content: { ...content, title: "Other project" },
    },
  };
  const draft = {
    id: "resume",
    name: "Resume",
    template_id: null,
    version: 1,
    items: [
      {
        project_id: "project",
        revision_id: "old",
        highlight_ids: ["a", "b", "c"],
      },
      { project_id: "other", revision_id: "other", highlight_ids: ["a"] },
    ],
  };
  return { content, revisions, draft };
}

test("uncommitted text, metadata and ordering appear without modifying fixed revisions", /* 验证草稿即刻进入预览，正式经历和组合引用不变 */ () => {
  const { content, revisions, draft } = fixture();
  const original = structuredClone({ revisions, draft });
  const working = {
    ...content,
    title: "Typing now",
    description: "Live description",
    highlights: [
      content.highlights[2],
      { ...content.highlights[0], text: "Live text" },
      content.highlights[1],
    ],
  };
  const result = buildLivePreview(
    draft,
    revisions,
    { old: working },
    "project",
    "old",
  );
  assert.equal(result.changed, true);
  assert.equal(result.sources.project.content, working);
  assert.deepEqual(
    result.sources.project.content.highlights.map(
      /* 检查当前显示顺序 */ (h) => h.id,
    ),
    ["c", "a", "b"],
  );
  assert.equal(result.sources.other, revisions.other);
  assert.deepEqual({ revisions, draft }, original);
});

test("switching editor revisions updates only that project's preview", /* 验证查看另一分支或版本不会串用其他项目内容或修改已固定版本 */ () => {
  const { revisions, draft } = fixture();
  const current = buildLivePreview(draft, revisions, {}, "project", "newer");
  assert.equal(current.sources.project.id, "newer");
  assert.equal(current.sources.project.content.title, "Newer project");
  assert.equal(draft.items[0].revision_id, "old");
  assert.equal(current.changed, true);
  const unrelated = buildLivePreview(draft, revisions, {}, "project", "other");
  assert.equal(unrelated.sources.project, revisions.old);
  assert.equal(unrelated.changed, false);
});

test("new draft highlights can be selected and reselected before committing", /* 验证新增未提交亮点可选择且按工作副本顺序预览 */ () => {
  const { content, revisions, draft } = fixture();
  const added = {
    id: "new",
    title: "New draft",
    text: "New text",
    evidence: [],
  };
  const working = { ...content, highlights: [added, ...content.highlights] };
  draft.items[0].highlight_ids = toggleHighlightSelection(
    working.highlights,
    ["a", "b", "c"],
    "new",
  );
  assert.equal(draft.items[0].highlight_ids.includes("new"), true);
  const result = buildLivePreview(
    draft,
    revisions,
    { old: working },
    "project",
    "old",
  );
  assert.equal(result.changed, true);
  assert.deepEqual(
    result.sources.project.content.highlights
      .filter(
        /* 模拟只显示勾选项 */ (h) =>
          draft.items[0].highlight_ids.includes(h.id),
      )
      .map(/* 提取预览顺序 */ (h) => h.id),
    ["new", "a", "b", "c"],
  );
});

test("removing and restoring a highlight follows the working copy while retaining its selection", /* 验证草稿删除即刻消失，取消删除后恢复原来的勾选状态 */ () => {
  const { content, revisions, draft } = fixture();
  const removed = {
    ...content,
    highlights: [content.highlights[0], content.highlights[2]],
  };
  const result = buildLivePreview(
    draft,
    revisions,
    { old: removed },
    "project",
    "old",
  );
  assert.equal(result.sources.project.content.highlights.length, 2);
  assert.deepEqual(draft.items[0].highlight_ids, ["a", "b", "c"]);
  const restored = buildLivePreview(
    draft,
    revisions,
    { old: content },
    "project",
    "old",
  );
  assert.equal(restored.sources.project.content.highlights.length, 3);
  assert.equal(restored.changed, false);
});

test("discarding draft order after toggling highlights restores the pinned export order", /* 排序草稿中取消再勾选后撤销草稿，导出顺序仍和固定版本预览一致 */ () => {
  const { content, revisions, draft } = fixture();
  const reordered = content.highlights.toReversed();
  const unchecked = toggleHighlightSelection(reordered, ["a", "b", "c"], "b");
  draft.items[0].highlight_ids = toggleHighlightSelection(
    reordered,
    unchecked,
    "b",
  );
  const before = structuredClone(draft);
  const ordered = orderCompositionHighlights(draft, revisions);
  assert.deepEqual(ordered.items[0].highlight_ids, ["a", "b", "c"]);
  assert.equal(
    buildLivePreview(ordered, revisions, {}, "project", "old").changed,
    false,
  );
  assert.deepEqual(draft, before);
  draft.items[0].highlight_ids.push("uncommitted");
  assert.deepEqual(
    orderCompositionHighlights(draft, revisions).items[0].highlight_ids,
    ["a", "b", "c", "uncommitted"],
  );
  assert.deepEqual(orderCompositionHighlights(draft, {}).items, draft.items);
});

test("saving and export become available only after the preview matches the chosen revision", /* 验证预览不会伪装成已经提交并用于简历的内容 */ () => {
  const { revisions, draft } = fixture();
  assert.equal(
    buildLivePreview(draft, revisions, {}, "project", "newer").changed,
    true,
  );
  draft.items[0].revision_id = "newer";
  assert.equal(
    buildLivePreview(draft, revisions, {}, "project", "newer").changed,
    false,
  );
  const loading = buildLivePreview(draft, {}, {}, "project", "newer");
  assert.deepEqual(loading.sources, {});
});
