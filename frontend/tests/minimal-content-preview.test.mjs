import assert from "node:assert/strict";
import test from "node:test";
import { buildSync } from "esbuild";
import { fileURLToPath } from "node:url";
import { newDocument, newEntry } from "../src/shared/resume/document.ts";
import { currentFitResult } from "../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/layoutFit.ts";

/** 渲染实际简历预览、注册表，验证模板缺席时仍能展示资料 */
async function composerPreview() {
  const output = buildSync({
    stdin: {
      contents: `import { createElement } from "react";
        import { renderToStaticMarkup } from "react-dom/server";
        import Composer from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/Composer";
        import LayoutSettings from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/LayoutSettings";
        import { LayoutSelectionContext } from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/layoutSelection";
        export { groupLayoutItems } from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/layoutItemGroups";
        export { stepLayoutNumber } from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/LayoutNumber";
        export { layoutItems } from "./src/shared/resume/itemLayout";
        export { default as ContentPreview } from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/ContentPreview";
        export { clientExtensions } from "./src/plugins/extensions";
        export function render(props) { return renderToStaticMarkup(createElement(Composer, props)); }
        export function renderSettings(props, key = "") {
          return renderToStaticMarkup(createElement(LayoutSelectionContext.Provider, {
            value: { key, request: key ? 1 : 0, select() {} },
          }, createElement(LayoutSettings, {
            document: props.draft.document,
            resumeIdentity: "test",
            previewInput: null,
            unavailable: false,
            onChange() {},
          })));
        }
        export function layoutSettingsProps(props) {
          let captured;
          function Inspect() {
            const preview = Composer(props);
            function visit(node) {
              if (Array.isArray(node)) { node.forEach(visit); return; }
              if (!node || typeof node !== "object") return;
              if (node.type === LayoutSettings) captured = node.props;
              visit(node.props?.children);
            }
            visit(preview.props.renderLayout(null, null));
            return null;
          }
          renderToStaticMarkup(createElement(Inspect));
          return captured;
        }`,
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

test("内容预览逐项应用格式，版面设置显示同类联动及四种参数", async () => {
  const module = await composerPreview();
  const props = fixture();
  props.onLayoutChange = () => {};
  props.draft.document.extensions = {
    "sys.resume.layout": {
      display: { hidden: true },
      options: {
        target_pages: 1,
        font_size: 10,
        honors_inline: true,
        item_styles: {
          types: {
            name: { font_size: 18 },
            highlight: {
              font_size: 9.5,
              space_before: 2,
              space_after: 3,
              line_spacing: 1.1,
            },
          },
          items: { '["project","project","description"]': { font_size: 12 } },
        },
      },
    },
  };
  const html = module.render(props);
  assert.match(html, /<h1 style="font-size:18pt"><button/);
  assert.match(html, /<p style="font-size:12pt"><button/);
  assert.match(
    html,
    /data-layout-key="\[&quot;personal&quot;,&quot;name&quot;\]"/,
  );
  assert.match(
    html,
    /<li style="font-size:9.5pt;margin-top:2pt;margin-bottom:3pt;line-height:1.1">/,
  );
  const settings = module.renderSettings(props, '["personal","name"]');
  assert.match(settings, /aria-label="断开同类联动" aria-pressed="true"/);
  assert.match(settings, /aria-label="所选项字号（磅）"/);
  assert.match(settings, /aria-label="所选项段前（磅）"/);
  assert.match(settings, /aria-label="所选项段后（磅）"/);
  assert.match(settings, /aria-label="所选项行距（倍）"/);
  assert.doesNotMatch(settings, /<select/);
  assert.doesNotMatch(html, /荣誉紧凑行|resume-layout-inline/);
});

test("恢复相同内容的另一份未保存稿会使旧压页响应失效", async () => {
  const module = await composerPreview();
  const props = fixture();
  props.onLayoutChange = () => {};
  props.draft.id = "";
  props.draft.draft_id = "draft-a";
  const original = module.layoutSettingsProps(props);
  props.draft = { ...props.draft, draft_id: "draft-b" };
  const restored = module.layoutSettingsProps(props);
  assert.equal(original.previewInput, restored.previewInput);
  assert.notEqual(original.resumeIdentity, restored.resumeIdentity);
  const active = {
    identity: JSON.stringify([
      original.resumeIdentity,
      original.previewInput,
      original.unavailable,
    ]),
    controller: new AbortController(),
  };
  assert.equal(currentFitResult(active, active, active.identity), true);
  assert.equal(
    currentFitResult(
      active,
      active,
      JSON.stringify([
        restored.resumeIdentity,
        restored.previewInput,
        restored.unavailable,
      ]),
    ),
    false,
  );
});

test("文字按栏目身份分组，重复栏目名称及个人信息同名标识不会混合", async () => {
  const module = await composerPreview();
  const document = newDocument();
  document.personal.name = "合成姓名";
  const education = document.sections.find(
    (section) => section.id === "education",
  );
  education.entries = [{ ...newEntry(), id: "school", title: "第一条目" }];
  document.sections.push({
    ...education,
    id: "personal",
    entries: [{ ...newEntry(), id: "school", title: "第二条目" }],
  });
  const items = module.layoutItems(document, []);
  const groups = module.groupLayoutItems(document, items);
  assert.ok(
    groups
      .find((group) => group.id === "personal")
      .items.every((item) => item.key.startsWith('["personal",')),
  );
  assert.ok(
    groups
      .find((group) => group.id === "section:education")
      .items.some((item) => item.label.includes("第一条目")),
  );
  assert.ok(
    groups
      .find((group) => group.id === "section:personal")
      .items.some((item) => item.label.includes("第二条目")),
  );
  assert.equal(groups.filter((group) => group.title === "教育背景").length, 2);
});

test("文字搜索覆盖完整长正文、栏目及类型，且不改变资料或选择标识", async () => {
  const module = await composerPreview();
  const document = newDocument();
  const education = document.sections.find(
    (section) => section.id === "education",
  );
  education.entries = [
    {
      ...newEntry(),
      id: "long",
      details: "前缀内容".repeat(20) + "尾部TargetAPI",
      title: "可见标题",
    },
  ];
  const items = module.layoutItems(document, []);
  const original = structuredClone({ document, items });
  const results = module.groupLayoutItems(document, items, "targetapi");
  assert.equal(results.length, 1);
  assert.deepEqual(
    results[0].items.map((item) => item.key),
    ['["entry","education","long","details"]'],
  );
  assert.ok(
    module.groupLayoutItems(document, items, "教育背景")[0].items.length > 1,
  );
  assert.equal(
    module.groupLayoutItems(document, items, "完全不存在的内容").length,
    0,
  );
  assert.deepEqual({ document, items }, original);
});

test("整体排版使用页数按钮、数值步进及继承重置，没有原生下拉框", async () => {
  const module = await composerPreview();
  const html = module.renderSettings(fixture());
  assert.match(html, /aria-label="页数预算"/);
  assert.match(html, /aria-pressed="true">1 页/);
  assert.match(html, /aria-label="减小正文字号"/);
  assert.match(html, /aria-label="增大正文字号"/);
  assert.match(html, /aria-label="正文字号恢复继承"/);
  assert.doesNotMatch(html, /<select/);
  const options = { min: 6, max: 72, step: 0.5, fallback: 10.5 };
  assert.equal(module.stepLayoutNumber(undefined, 1, options), 10.5);
  assert.equal(module.stepLayoutNumber(10.5, 1, options), 11);
  assert.equal(module.stepLayoutNumber(6, -1, options), 6);
  assert.equal(module.stepLayoutNumber(72, 1, options), 72);
  assert.equal(
    module.stepLayoutNumber(9.75, 1, { ...options, halfPoints: true }),
    10,
  );
  assert.equal(
    module.stepLayoutNumber(9.75, -1, { ...options, halfPoints: true }),
    9.5,
  );
  assert.equal(
    module.stepLayoutNumber(1.025, 1, {
      min: 0.8,
      max: 3,
      step: 0.05,
      fallback: 1.2,
    }),
    1.075,
  );
});
