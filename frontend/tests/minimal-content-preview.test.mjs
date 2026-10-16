import assert from "node:assert/strict";
import test from "node:test";
import { buildSync } from "esbuild";
import { fileURLToPath } from "node:url";
import { newDocument } from "../src/shared/resume/document.ts";

/** 渲染实际简历预览、注册表，验证模板缺席时仍能展示资料 */
async function composerPreview() {
  const output = buildSync({
    stdin: {
      contents: `import { createElement } from "react";
        import { renderToStaticMarkup } from "react-dom/server";
        import Composer from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/Composer";
        export { default as ContentPreview } from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ContentPreview";
        export { clientExtensions } from "./src/plugins/extensions";
        export function render(props) { return renderToStaticMarkup(createElement(Composer, props)); }`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    platform: "node",
    format: "esm",
    jsx: "automatic",
    tsconfigRaw: {},
    nodePaths: [fileURLToPath(new URL("../node_modules", import.meta.url))],
    external: [
      "react",
      "react-dom/server",
      "react/jsx-runtime",
      "lucide-react",
    ],
    alias: {
      "@resume-maker/plugin-sdk": fileURLToPath(
        new URL("../src/plugins/shared/exports", import.meta.url),
      ),
    },
    write: false,
  }).outputFiles[0].text;
  let source = output;
  for (const name of [
    "react",
    "react-dom/server",
    "react/jsx-runtime",
    "lucide-react",
  ])
    source = source.replaceAll(
      JSON.stringify(name),
      JSON.stringify(import.meta.resolve(name)),
    );
  return import(
    `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
  );
}

/** 构造切换到极简模式后仍引用扩展模板的简历及编辑副本 */
function fixture() {
  const document = newDocument();
  document.personal.name = "示例姓名";
  document.personal.phone = "隐藏联系方式";
  document.personal.hidden_fields = ["phone"];
  const revision = {
    id: "revision",
    project_id: "project",
    content: {
      title: "示例项目",
      period: "2026",
      role: "开发工程师",
      stack: ["Python"],
      description: "已提交正文",
      highlights: [
        { id: "selected", title: "选中亮点", text: "亮点正文" },
        { id: "other", title: "未选中亮点", text: "未选中正文" },
      ],
    },
  };
  return {
    state: { templates: [] },
    draft: {
      name: "合成简历",
      template_id: "disabled-template",
      document,
      items: [
        {
          project_id: "project",
          revision_id: "revision",
          highlight_ids: ["selected"],
        },
      ],
    },
    revisions: { revision },
    previewSources: {
      project: {
        ...revision,
        content: { ...revision.content, description: "正在编辑的正文" },
      },
    },
    previewFocused: false,
    onFocusPreview() {},
    exporting: false,
    deleting: false,
    onGenerate() {},
    run() {},
  };
}

test("极简模式保留原模板引用并预览当前资料、选中亮点和编辑副本", async () => {
  const module = await composerPreview();
  const props = fixture();
  const original = structuredClone({
    draft: props.draft,
    revisions: props.revisions,
    sources: props.previewSources,
  });
  const html = module.render(props);
  for (const text of [
    "已切换为内容预览",
    "简历内容预览",
    "示例姓名",
    "示例项目",
    "正在编辑的正文",
    "选中亮点",
  ])
    assert.ok(html.includes(text), text);
  for (const text of [
    "隐藏联系方式",
    "未选中亮点",
    "已提交正文",
    "正在读取经历版本",
  ])
    assert.ok(!html.includes(text), text);
  assert.deepEqual(
    {
      draft: props.draft,
      revisions: props.revisions,
      sources: props.previewSources,
    },
    original,
  );
});

test("模板缺席时跳过 Word，模板可用和内置排版时仍优先选择 Word", async () => {
  const module = await composerPreview();
  let wordCalls = 0;
  const dispose = module.clientExtensions.contribute(
    {
      id: "ext.word",
      contributes: { "documents.previewers": ["ext.word/pages"] },
    },
    "documents.previewers",
    "ext.word/pages",
    {
      title: "Word 精确分页",
      formats: ["resume/v1"],
      component() {
        wordCalls++;
        return "Word 分页预览";
      },
    },
  );
  try {
    const props = fixture();
    assert.ok(module.render(props).includes("简历内容预览"));
    assert.equal(wordCalls, 0);
    props.state.templates = [{ id: props.draft.template_id }];
    assert.ok(module.render(props).includes("Word 分页预览"));
    props.draft.template_id = null;
    props.state.templates = [];
    assert.ok(module.render(props).includes("Word 分页预览"));
    assert.equal(wordCalls, 2);
  } finally {
    await dispose();
  }
});

test("极简模式的新简历通过系统预览器独立展示内容", async () => {
  const module = await composerPreview();
  const dispose = module.clientExtensions.contribute(
    {
      id: "sys.resume",
      contributes: { "documents.previewers": ["sys.resume/content"] },
    },
    "documents.previewers",
    "sys.resume/content",
    {
      title: "内容预览",
      formats: ["resume/v1"],
      component: module.ContentPreview,
    },
  );
  try {
    const props = fixture();
    props.draft.template_id = null;
    const html = module.render(props);
    assert.ok(html.includes("简历内容预览"));
    assert.ok(html.includes("正在编辑的正文"));
    assert.ok(!html.includes("已切换为内容预览"));
  } finally {
    await dispose();
  }
});

test("预览方式放入工具栏，排版内容及插件参数保持独立", async () => {
  const module = await composerPreview();
  const disposers = [
    module.clientExtensions.contribute(
      {
        id: "sys.resume",
        contributes: { "documents.previewers": ["sys.resume/content"] },
      },
      "documents.previewers",
      "sys.resume/content",
      {
        title: "内容预览",
        formats: ["resume/v1"],
        component: module.ContentPreview,
      },
    ),
    module.clientExtensions.contribute(
      {
        id: "ext.word",
        contributes: { "documents.previewers": ["ext.word/pages"] },
      },
      "documents.previewers",
      "ext.word/pages",
      {
        title: "Word 精确分页",
        formats: ["resume/v1"],
        component(props) {
          assert.equal("renderLayout" in props, false);
          assert.equal("preferred" in props, false);
          return "Word 分页内容";
        },
      },
    ),
  ];
  try {
    const props = fixture();
    props.draft.template_id = null;
    const html = module.render(props);
    const boundary = html.indexOf('<div class="composition-scroll">');
    assert.ok(boundary > 0);
    assert.ok(html.slice(0, boundary).includes('aria-label="预览方式"'));
    assert.ok(!html.slice(boundary).includes('aria-label="预览方式"'));
    assert.ok(html.slice(boundary).includes("Word 分页内容"));
  } finally {
    for (const dispose of disposers) await dispose();
  }
});

test("缺失固定版本时等待加载，尚未填写资料时显示填写指引", async () => {
  const module = await composerPreview();
  const props = fixture();
  props.revisions = {};
  assert.ok(module.render(props).includes("正在读取经历版本"));
  props.draft.document = null;
  const html = module.render(props);
  assert.ok(html.includes("填写个人资料后"));
  assert.ok(!html.includes("正在读取经历版本"));
  assert.ok(!html.includes("已切换为内容预览"));
});

test("未固定的经历内容明确提示尚未采用，应用后恢复简历预览", async () => {
  const module = await composerPreview();
  const props = fixture();
  props.previewChanged = true;
  const pending = module.render(props);
  assert.ok(pending.includes("经历预览 · 尚未用于简历"));
  assert.ok(pending.includes("或采用已保存版本"));
  props.previewChanged = false;
  const applied = module.render(props);
  assert.ok(applied.includes(">简历预览</strong>"));
  assert.ok(!applied.includes("经历预览 · 尚未用于简历"));
});

test("生成入口保留在预览工具栏，模板缺失、经历未采用及生成期间禁止提交", async () => {
  const module = await composerPreview();
  const props = fixture();
  const unavailable = module.render(props);
  assert.match(unavailable, /disabled="" title="请在当前简历中选择可用排版"/);
  props.draft.template_id = null;
  props.previewChanged = true;
  assert.match(
    module.render(props),
    /disabled="" title="先将编辑内容保存并用于当前简历/,
  );
  props.previewChanged = false;
  const ready = module.render(props);
  const boundary = ready.indexOf('<div class="composition-scroll">');
  assert.ok(ready.slice(0, boundary).includes("生成简历"));
  assert.ok(!ready.slice(boundary).includes("生成简历"));
  props.exporting = true;
  assert.ok(module.render(props).includes("正在生成简历…"));
});
