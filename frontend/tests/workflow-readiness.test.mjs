import assert from "node:assert/strict";
import { test } from "node:test";
import { buildSync } from "esbuild";
import { fileURLToPath } from "node:url";
import { getWorkflow } from "../../src/resume_maker/plugin_packages/ext_workflow/client/state.ts";
import { readinessCounts } from "../../src/resume_maker/plugin_packages/ext_workflow/client/readiness.ts";
import { WORKFLOW_STEPS } from "../../src/resume_maker/plugin_packages/ext_workflow/client/steps.ts";
import { newDocument, newEntry } from "../src/shared/resume/document.ts";

/** 构造新建简历，项目库及荣誉库均无资料 */
function fixture() {
  return {
    projectCount: 0,
    detail: null,
    revisionId: "",
    edited: false,
    revisions: {},
    draft: {
      id: "",
      draft_id: "synthetic",
      name: "测试简历",
      version: 0,
      template_id: null,
      items: [],
      document: newDocument(),
    },
    result: null,
    exporting: false,
    analyzing: false,
  };
}

test("新简历区分内置版式可直接使用及空白可选栏目，不虚报完成", () => {
  const state = fixture();
  const value = getWorkflow(state);
  assert.deepEqual(value.statuses, [
    "ready",
    "pending",
    "optional",
    "optional",
    "pending",
    "pending",
  ]);
  assert.deepEqual(readinessCounts(value.statuses), {
    complete: 0,
    ready: 1,
    optional: 2,
    skipped: 0,
  });
  assert.equal(value.done[2], false);
  assert.equal(value.done[3], false);
  assert.match(value.guides[0].text, /已选择内置完整简历/);
  assert.equal(value.target, "personal-basic");
});

test("新建未用于简历的空项目不会回退准备状态，手工路径直接定位编辑", () => {
  const state = fixture();
  const before = getWorkflow(state);
  state.projectCount = 1;
  state.revisionId = "empty";
  const content = {
    title: "手工项目",
    description: "",
    period: "",
    role: "",
    stack: [],
    highlights: [],
  };
  state.detail = {
    project: { id: "project" },
    working: { content, drafts: [] },
  };
  state.revisions.empty = { id: "empty", project_id: "project", content };
  const after = getWorkflow(state);
  assert.deepEqual(after.statuses, before.statuses);
  assert.equal(after.guides[2].target, "experience-save");
  assert.equal(after.guides[2].action, "编辑经历");
  assert.equal(WORKFLOW_STEPS[2].substeps[1].target, "experience-save");
});

test("明确隐藏的可选栏目显示已跳过，重新显示仍可填写", () => {
  const state = fixture();
  for (const section of state.draft.document.sections)
    if (section.kind === "projects" || section.id === "honors")
      section.visible = false;
  const skipped = getWorkflow(state);
  assert.equal(skipped.statuses[2], "skipped");
  assert.equal(skipped.statuses[3], "skipped");
  assert.equal(readinessCounts(skipped.statuses).skipped, 2);
  assert.equal(skipped.done[2], false);
  assert.equal(skipped.done[3], false);
  for (const section of state.draft.document.sections) section.visible = true;
  assert.equal(getWorkflow(state).statuses[2], "optional");
  assert.equal(getWorkflow(state).statuses[3], "optional");
});

test("无项目及荣誉的合法简历仍可完成资料、保存及导出", () => {
  const state = fixture();
  state.draft.id = "resume";
  state.draft.document.personal.name = "合成同学";
  state.draft.document.personal.email = "synthetic@example.test";
  for (const id of ["education", "skills"])
    state.draft.document.sections.find((section) => section.id === id).entries =
      [{ ...newEntry(), title: "合成资料" }];
  state.saved = structuredClone(state.draft);
  state.result = {
    resume_id: "resume",
    manifest: { resume: structuredClone(state.draft) },
  };
  const value = getWorkflow(state);
  assert.deepEqual(value.statuses, [
    "ready",
    "complete",
    "optional",
    "optional",
    "complete",
    "complete",
  ]);
  assert.equal(value.target, "export");
  assert.deepEqual(readinessCounts(value.statuses), {
    complete: 3,
    ready: 1,
    optional: 2,
    skipped: 0,
  });
});

/** 使用实际工作流组件验证状态名称及统计，避免文字和计算规则脱节 */
async function renderWorkflow(input) {
  const external = [
    "react",
    "react-dom/server",
    "react/jsx-runtime",
    "lucide-react",
  ];
  let source = buildSync({
    stdin: {
      contents: `import {createElement} from "react";
        import {renderToStaticMarkup} from "react-dom/server";
        import Workflow from "../src/resume_maker/plugin_packages/ext_workflow/client/Workflow";
        export function render(input) { return renderToStaticMarkup(createElement(Workflow, {input, activeStep:2, collapsed:false, onToggle(){}, onNavigate(){}})); }`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    platform: "node",
    format: "esm",
    jsx: "automatic",
    tsconfigRaw: {},
    nodePaths: [fileURLToPath(new URL("../node_modules", import.meta.url))],
    external,
    alias: {
      "@resume-maker/plugin-sdk": fileURLToPath(
        new URL("../src/plugins/shared/exports", import.meta.url),
      ),
    },
    write: false,
  }).outputFiles[0].text;
  for (const name of external)
    source = source.replaceAll(
      JSON.stringify(name),
      JSON.stringify(import.meta.resolve(name)),
    );
  const previousDocument = globalThis.document;
  globalThis.document = { querySelector: () => null };
  try {
    const module = await import(
      `data:text/javascript;base64,${Buffer.from(source + "\n//# sourceURL=workflow-render-test.mjs").toString("base64")}`
    );
    return module.render(input);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
}

test("实际制作指引分别展示已选择、可跳过，手工步骤不要求智能整理", async () => {
  const html = await renderWorkflow(fixture());
  assert.ok(html.includes("已选择 · 可直接使用"));
  assert.ok(html.includes("项目经历，可跳过"));
  assert.ok(html.includes("荣誉证书，可跳过"));
  assert.ok(html.includes("可跳过 2 项"));
  assert.ok(html.includes("编辑经历"));
  assert.ok(!html.includes("智能整理"));
  assert.ok(!html.includes("项目经历，已完成"));
});
