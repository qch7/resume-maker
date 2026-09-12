import { test } from "node:test";
import assert from "node:assert/strict";
import { getWorkflow, isCurrentExport } from "../src/workflowState.ts";

function fixture() {
  const content = {
    title: "测试项目",
    description: "已核实的项目描述",
    highlights: [],
    role: "",
    period: "",
    stack: [],
  };
  const revision = { id: "r2", project_id: "p1", number: 2, content };
  const draft = {
    id: "resume",
    name: "我的简历",
    template_id: "template",
    version: 1,
    items: [{ project_id: "p1", revision_id: "r2", highlight_ids: [] }],
  };
  return {
    projectCount: 1,
    detail: { project: { id: "p1" }, working: { content, drafts: [] } },
    revisionId: "r2",
    edited: false,
    draft,
    saved: structuredClone(draft),
    revisions: { r2: revision },
    result: null,
    exporting: false,
    analyzing: false,
  };
}

test("new workspace starts at import", () => {
  const state = fixture();
  state.projectCount = 0;
  state.detail = null;
  state.revisions = {};
  assert.equal(getWorkflow(state).target, "projects");
  assert.deepEqual(getWorkflow(state).done, [false, false, false, false]);
});

test("typing and recovered server drafts both require a saved revision", () => {
  const state = fixture();
  state.edited = true;
  assert.equal(getWorkflow(state).target, "experience-save");
  assert.deepEqual(getWorkflow(state).done, [true, false, false, false]);
  state.edited = false;
  state.detail.working.drafts = [{ field: "highlight:h1" }];
  assert.equal(getWorkflow(state).target, "experience-save");
});

test("saved experience must be explicitly added or used to replace a pinned revision", () => {
  const state = fixture();
  state.draft.items = [];
  assert.equal(getWorkflow(state).target, "experience-use");
  state.draft.items = [
    { project_id: "p1", revision_id: "r1", highlight_ids: [] },
  ];
  state.revisions.r1 = { ...state.revisions.r2, id: "r1", number: 1 };
  const guide = getWorkflow(state);
  assert.match(guide.text, /r2.*r1/);
  assert.equal(guide.target, "experience-use");
});

test("an empty project in a multi-project resume is identified for editing", () => {
  const state = fixture();
  state.revisions.r3 = {
    ...state.revisions.r2,
    id: "r3",
    project_id: "p2",
    content: { ...state.revisions.r2.content, description: "" },
  };
  state.draft.items.push({
    project_id: "p2",
    revision_id: "r3",
    highlight_ids: [],
  });
  assert.equal(getWorkflow(state).projectId, "p2");
  assert.equal(getWorkflow(state).target, "experience-save");
});

test("changed composition and missing template have actionable steps", () => {
  const state = fixture();
  state.draft.name = "投递另一岗位";
  assert.equal(getWorkflow(state).target, "composition-save");
  state.saved = structuredClone(state.draft);
  state.draft.template_id = null;
  state.saved.template_id = null;
  assert.equal(getWorkflow(state).target, "template-select");
});

test("export completion compares actual composition, not just existence or save counter", () => {
  const state = fixture();
  state.result = {
    resume_id: "resume",
    pages: 2,
    manifest: { resume: structuredClone(state.draft) },
  };
  state.draft.version += 1;
  assert.equal(isCurrentExport(state.result, state.draft), true);
  assert.deepEqual(getWorkflow(state).done, [true, true, true, true]);
  state.draft.items[0].highlight_ids.push("h1");
  assert.equal(isCurrentExport(state.result, state.draft), false);
  state.saved = structuredClone(state.draft);
  assert.match(getWorkflow(state).text, /上次导出仍是旧内容/);
});

test("historical exports cannot complete a new resume or an empty composition", () => {
  const state = fixture();
  state.result = {
    resume_id: "another-resume",
    pages: 2,
    manifest: { resume: structuredClone(state.draft) },
  };
  assert.equal(isCurrentExport(state.result, state.draft), false);
  state.revisions.r2.content.description = "";
  assert.deepEqual(getWorkflow(state).done, [true, false, false, false]);
});

test("export in progress has no invented percentage and generated Word needs no PDF to complete", () => {
  const state = fixture();
  state.exporting = true;
  assert.match(getWorkflow(state).text, /正在生成/);
  state.exporting = false;
  state.result = {
    resume_id: "resume",
    pages: null,
    render_error: "Word unavailable",
    manifest: { resume: structuredClone(state.draft) },
  };
  assert.equal(getWorkflow(state).done[3], true);
  assert.match(getWorkflow(state).text, /Word 已生成/);
});
