import { test } from "node:test";
import assert from "node:assert/strict";
import { getWorkflow } from "../src/features/workflow/state.ts";
import { isCurrentExport } from "../src/features/resumes/composition.ts";
import { newDocument, newEntry } from "../src/features/profile/document.ts";

/* 构造隔离的项目、组合和导出状态，供制作流程测试复用 */ function fixture() {
  const content = {
    title: "测试项目",
    description: "已核实的项目描述",
    highlights: [],
    role: "",
    period: "",
    stack: [],
  };
  const revision = { id: "r2", project_id: "p1", number: 2, content };
  const document = newDocument();
  document.personal.name = "测试同学";
  document.personal.email = "resume@example.com";
  for (const id of ["education", "honors", "skills"]) {
    document.sections.find((section) => section.id === id).entries = [
      { ...newEntry(), title: `${id} 已填写` },
    ];
  }
  const draft = {
    id: "resume",
    name: "我的简历",
    template_id: "template",
    version: 1,
    document,
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

test("new workspace starts at template recognition", /* 从模板开始统计整份简历的制作进度 */ () => {
  const state = fixture();
  state.projectCount = 0;
  state.detail = null;
  state.revisions = {};
  state.draft.template_id = null;
  state.draft.document = null;
  assert.equal(getWorkflow(state).target, "template-select");
  assert.deepEqual(getWorkflow(state).done, [
    false,
    false,
    false,
    false,
    false,
    false,
  ]);
  assert.equal(getWorkflow(state).guides[2].target, "projects");
});

test("typing and recovered server drafts both require a saved revision", /* 验证本机编辑和恢复的草稿都不能当作正式保存 */ () => {
  const state = fixture();
  state.edited = true;
  assert.equal(getWorkflow(state).target, "experience-save");
  assert.deepEqual(getWorkflow(state).done, [
    true,
    true,
    false,
    true,
    false,
    false,
  ]);
  state.edited = undefined;
  state.detail.working.content = {
    ...state.detail.working.content,
    description: "恢复的草稿",
  };
  state.detail.working.drafts = [{ field: "highlight:h1" }];
  assert.equal(getWorkflow(state).target, "experience-save");
});

test("恢复原值的草稿记录不阻止制作流程", /* 服务器仍保留并发版本记录时也只比较正文差异 */ () => {
  const state = fixture();
  state.edited = undefined;
  state.detail.working.drafts = [{ field: "meta" }];
  assert.equal(getWorkflow(state).target, "export");
  state.edited = false;
  state.detail.working.content = {
    ...state.detail.working.content,
    description: "过期远端内容",
  };
  assert.equal(getWorkflow(state).target, "export");
});

test("saved experience must be explicitly added or used to replace a pinned revision", /* 验证新版本只有显式用于简历后才替换固定引用 */ () => {
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

test("an empty project in a multi-project resume is identified for editing", /* 验证多项目组合可定位尚无内容的经历 */ () => {
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

test("changed composition and missing template have actionable steps", /* 验证组合改变或缺少模板时给出可操作的指引 */ () => {
  const state = fixture();
  state.draft.name = "投递另一岗位";
  assert.equal(getWorkflow(state).target, "composition-save");
  state.saved = structuredClone(state.draft);
  state.draft.template_id = null;
  state.saved.template_id = null;
  state.draft.document = null;
  state.saved.document = null;
  assert.equal(getWorkflow(state).target, "template-select");
});

test("export completion compares actual composition, not just existence or save counter", /* 验证导出完成状态比较真实组合内容 */ () => {
  const state = fixture();
  state.result = {
    resume_id: "resume",
    pages: 2,
    manifest: { resume: structuredClone(state.draft) },
  };
  state.draft.version += 1;
  assert.equal(isCurrentExport(state.result, state.draft), true);
  assert.deepEqual(getWorkflow(state).done, [
    true,
    true,
    true,
    true,
    true,
    true,
  ]);
  state.draft.items[0].highlight_ids.push("h1");
  assert.equal(isCurrentExport(state.result, state.draft), false);
  state.saved = structuredClone(state.draft);
  assert.match(getWorkflow(state).text, /上次导出仍是旧内容/);
});

test("historical exports cannot complete a new resume or an empty composition", /* 验证其他简历或空组合不能复用历史导出的完成状态 */ () => {
  const state = fixture();
  state.result = {
    resume_id: "another-resume",
    pages: 2,
    manifest: { resume: structuredClone(state.draft) },
  };
  assert.equal(isCurrentExport(state.result, state.draft), false);
  state.revisions.r2.content.description = "";
  assert.deepEqual(getWorkflow(state).done, [
    true,
    true,
    false,
    true,
    false,
    false,
  ]);
});

test("export in progress has no invented percentage and generated Word needs no PDF to complete", /* 验证导出过程不显示虚构百分比，DOCX 可独立完成 */ () => {
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
  assert.equal(getWorkflow(state).done[5], true);
  assert.match(getWorkflow(state).text, /Word 已生成/);
});

test("personal guidance locates missing basic, education and skills content", /* 姓名和联系方式就绪后，按具体栏目引导补全资料 */ () => {
  const state = fixture();
  state.draft.document = newDocument();
  assert.equal(getWorkflow(state).target, "personal-basic");
  state.draft.document.personal.name = "测试同学";
  state.draft.document.personal.phone = "12345678900";
  assert.equal(getWorkflow(state).target, "personal-education");
  const education = state.draft.document.sections.find(
    (section) => section.id === "education",
  );
  education.entries = [{ ...newEntry(), title: "   " }];
  assert.equal(getWorkflow(state).target, "personal-education");
  education.entries[0].title = "示例大学";
  assert.equal(getWorkflow(state).target, "personal-skills");
  const skills = state.draft.document.sections.find(
    (section) => section.id === "skills",
  );
  skills.entries = [{ ...newEntry(), details: "TypeScript、Python" }];
  assert.equal(getWorkflow(state).done[1], true);
  assert.deepEqual(getWorkflow(state).substeps[1], [
    true,
    true,
    true,
    false,
    true,
  ]);
});

test("recognized honors must be selected into this resume to complete the honor step", /* 识别完成和用于当前简历是两个独立步骤 */ () => {
  const state = fixture();
  const honors = state.draft.document.sections.find(
    (section) => section.id === "honors",
  );
  honors.entries = [];
  state.honors = [{ id: "h1", reviewed: false, fields: { name: "示例奖项" } }];
  assert.equal(getWorkflow(state).target, "honor-recognize");
  state.honors[0].reviewed = true;
  assert.equal(getWorkflow(state).target, "honor-select");
  assert.deepEqual(getWorkflow(state).substeps[3], [true, false]);
  // 按来源标识识别加入自定义栏目的荣誉
  state.draft.document.sections
    .find((section) => section.id === "skills")
    .entries.push({ ...newEntry(), id: "honor:h1", title: "示例奖项" });
  assert.deepEqual(getWorkflow(state).substeps[3], [true, true]);
  assert.equal(getWorkflow(state).done[3], true);
});

test("hidden and empty content cannot falsely complete a visible section", /* 检查字段显隐和父栏目显隐对准备状态的影响 */ () => {
  const state = fixture();
  const education = state.draft.document.sections.find(
    (section) => section.id === "education",
  );
  education.entries[0].hidden_fields = ["title"];
  assert.equal(getWorkflow(state).done[1], false);
  education.visible = false;
  assert.equal(getWorkflow(state).done[1], true);
  const honors = state.draft.document.sections.find(
    (section) => section.id === "honors",
  );
  honors.entries = [];
  honors.parent_id = education.id;
  assert.equal(getWorkflow(state).done[3], true);
});

test("personal edits invalidate saved composition and the previous export", /* 导出进度比较整份简历内容 */ () => {
  const state = fixture();
  state.result = {
    resume_id: "resume",
    pages: 1,
    manifest: { resume: structuredClone(state.draft) },
  };
  assert.equal(getWorkflow(state).done[5], true);
  state.draft.document.personal.phone = "12345678900";
  assert.equal(getWorkflow(state).done[4], false);
  assert.equal(getWorkflow(state).done[5], false);
  assert.equal(getWorkflow(state).target, "composition-save");
});

test("built-in full resume is a usable template without a template id", /* 内置版式不创建模板记录，也能完成模板步骤 */ () => {
  const state = fixture();
  state.draft.template_id = null;
  state.saved = structuredClone(state.draft);
  assert.equal(getWorkflow(state).done[0], true);
  assert.equal(getWorkflow(state).target, "export");
  assert.match(getWorkflow(state).guides[0].text, /内置/);
});
