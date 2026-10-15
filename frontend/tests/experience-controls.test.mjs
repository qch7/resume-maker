import assert from "node:assert/strict";
import { test } from "node:test";
import { buildSync } from "esbuild";
import { fileURLToPath } from "node:url";

/** 在内存中构建实际经历控件，使用 React 静态渲染验证展示状态 */
async function experienceComponents() {
  const external = [
    "react",
    "react-dom",
    "react-dom/server",
    "react/jsx-runtime",
    "lucide-react",
    "@dnd-kit/core",
    "@dnd-kit/sortable",
    "@dnd-kit/utilities",
  ];
  const output = buildSync({
    stdin: {
      contents: `import { createElement } from "react";
        import { renderToStaticMarkup } from "react-dom/server";
        import VersionControl from "../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/VersionControl";
        import Editor from "../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/Editor";
        export function controls(props) { return renderToStaticMarkup(createElement(VersionControl, { props })); }
        export function editor(props) { return renderToStaticMarkup(createElement(Editor, props)); }`,
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
  let source = output;
  for (const name of external)
    source = source.replaceAll(
      JSON.stringify(name),
      JSON.stringify(import.meta.resolve(name)),
    );
  const previousDocument = globalThis.document;
  globalThis.document = { querySelector: () => null };
  try {
    return await import(
      `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
    );
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
}

const components = await experienceComponents();

/** 构造包含项目资料、亮点、分支及已保存版本的独立编辑器输入 */
function fixture() {
  const content = {
    title: "合成测试项目",
    period: "2026",
    role: "开发工程师",
    stack: ["TypeScript"],
    description: "已保存的项目描述",
    highlights: [
      {
        id: "point",
        title: "测试亮点",
        text: "已保存的亮点正文",
        evidence: [],
      },
    ],
  };
  const revision = {
    id: "r2",
    project_id: "project",
    number: 2,
    content,
    branch_id: "main",
    branch_name: "主分支",
  };
  const branch = {
    id: "main",
    name: "主分支",
    is_default: true,
    head_revision: revision.id,
  };
  return {
    detail: {
      project: {
        id: "project",
        name: "测试项目",
        roots: [],
        profile: {
          role: "本人开发角色",
          period: "2026",
          contribution: "合成贡献内容",
          outcomes: "合成成果内容",
          notes: "",
        },
      },
      revision,
      branch,
      branches: [branch],
      working: { content: structuredClone(content), drafts: [] },
      revision_snapshot: null,
      snapshots: [],
    },
    revisionId: revision.id,
    included: ["point"],
    visibility: {},
    hasLocalChanges: false,
    saving: false,
    run() {},
    async onSave() {},
    async onDiscard() {},
    onRefresh() {},
    onRevision() {},
    onUseVersion() {},
    async onAsk() {},
    onToggle() {},
    onPreview() {},
    onVisibility() {},
  };
}

/** 从渲染结果读取指定按钮的可见名称、禁用状态 */
function button(html, label) {
  const found = [
    ...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g),
  ].find((match) => match[2].replace(/<[^>]*>/g, "").trim() === label);
  assert.ok(found, `缺少按钮：${label}`);
  return {
    attributes: found[1],
    disabled: /\bdisabled(?:=|\s|$)/.test(found[1]),
  };
}

test("最新版本存在草稿时展示一键应用主操作及独立保存入口", () => {
  const props = fixture();
  props.hasLocalChanges = true;
  props.usedRevision = props.detail.revision;
  const html = components.controls(props);
  const primary = button(html, "保存并用于当前简历");
  assert.match(primary.attributes, /class="primary"/);
  assert.match(primary.attributes, /data-guide="experience-save"/);
  assert.equal(primary.disabled, false);
  assert.equal(button(html, "仅保存版本").disabled, false);
});

test("已保存版本可应用，当前已引用版本明确显示完成且阻止重复操作", () => {
  const props = fixture();
  const unapplied = components.controls(props);
  assert.equal(button(unapplied, "用于当前简历").disabled, false);
  assert.equal(button(unapplied, "仅保存版本").disabled, true);
  props.usedRevision = props.detail.revision;
  const applied = components.controls(props);
  assert.equal(button(applied, "已用于当前简历").disabled, true);
  assert.equal(button(applied, "仅保存版本").disabled, true);
});

test("历史版本有草稿时阻止发布，完整历史版本仍可用于简历", () => {
  const props = fixture();
  props.detail.branch.head_revision = "r3";
  props.hasLocalChanges = true;
  const pending = components.controls(props);
  assert.equal(button(pending, "保存并用于当前简历").disabled, true);
  assert.equal(button(pending, "仅保存版本").disabled, true);
  assert.match(pending, /历史版本/);
  props.hasLocalChanges = false;
  const saved = components.controls(props);
  assert.equal(button(saved, "用于当前简历").disabled, false);
  assert.equal(button(saved, "仅保存版本").disabled, true);
});

test("保存期间展示进行状态并禁用两种保存操作", () => {
  for (const pending of [false, true]) {
    const props = fixture();
    props.hasLocalChanges = pending;
    props.saving = true;
    const html = components.controls(props);
    assert.equal(button(html, "正在保存…").disabled, true);
    assert.equal(button(html, "仅保存版本").disabled, true);
  }
});

test("实际编辑器区分正式版本及草稿，保存锁覆盖全部内容控件", () => {
  const props = fixture();
  const saved = components.editor(props);
  assert.match(saved, /经历版本已保存/);
  assert.doesNotMatch(saved, /经历草稿 · 尚未保存为版本/);
  const unlocked = saved.match(/^<fieldset\b([^>]*)>/);
  assert.ok(unlocked);
  assert.doesNotMatch(unlocked[1], /\bdisabled(?:=|\s|$)/);
  assert.match(unlocked[1], /aria-busy="false"/);

  props.detail.working.content.description = "等待保存的最新描述";
  props.saving = true;
  const pending = components.editor(props);
  const locked = pending.match(/^<fieldset\b([^>]*)>/);
  assert.ok(locked);
  assert.match(locked[1], /\bdisabled=""/);
  assert.match(locked[1], /aria-label="项目经历编辑"/);
  assert.match(locked[1], /aria-busy="true"/);
  assert.ok(pending.endsWith("</fieldset>"));
  assert.doesNotMatch(pending, /<legend\b/);
  for (const text of [
    "经历草稿 · 尚未保存为版本",
    "等待保存的最新描述",
    "测试亮点",
    "合成贡献内容",
    "保存来源路径",
  ])
    assert.ok(pending.includes(text), `锁内缺少内容：${text}`);
  assert.match(pending, /<textarea\b/);
  assert.equal(button(pending, "正在保存…").disabled, true);
  assert.equal(button(pending, "仅保存版本").disabled, true);
});
