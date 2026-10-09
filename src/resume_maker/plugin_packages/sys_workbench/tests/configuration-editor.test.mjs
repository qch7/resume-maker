import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  changeConfigField,
  changeConfigJson,
  configFields,
  emptyConfigDraft,
  resetConfigField,
} from "../client/features/plugins/configurationForm.ts";

const require = createRequire(
  new URL("../../../../../frontend/package.json", import.meta.url),
);
const { buildSync } = require("esbuild");
const rapidocr = JSON.parse(
  readFileSync(
    new URL("../../provider_rapidocr/manifest.json", import.meta.url),
    "utf8",
  ),
);
const fields = configFields(rapidocr.config_schema);
const threads = fields.find(
  (field) => field.path[0] === "intra_op_num_threads",
);

/** 渲染实际表单组件，使用 React 上下文执行 useId */
async function editor() {
  let source = buildSync({
    stdin: {
      contents: `import { createElement } from "react";
        import { renderToStaticMarkup } from "react-dom/server";
        import Editor from "../client/features/plugins/PluginConfigEditor";
        export function render(props) {
          return renderToStaticMarkup(createElement(Editor, props));
        }`,
      resolveDir: fileURLToPath(new URL("./", import.meta.url)),
    },
    bundle: true,
    platform: "node",
    format: "esm",
    jsx: "automatic",
    tsconfigRaw: {},
    external: ["react", "react-dom/server", "react/jsx-runtime"],
    write: false,
  }).outputFiles[0].text;
  for (const name of ["react", "react-dom/server", "react/jsx-runtime"])
    source = source.replaceAll(
      `"${name}"`,
      JSON.stringify(pathToFileURL(require.resolve(name)).href),
    );
  return import(
    `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
  );
}

const { render } = await editor();
const props = {
  title: "RapidOCR",
  schema: rapidocr.config_schema,
  value: rapidocr.config,
  provenance: Object.fromEntries(
    fields.map((field) => [field.pointer, "default"]),
  ),
  draft: emptyConfigDraft(),
  disabled: false,
  onChange: () => {},
};

test("凭据字段使用空密码控件，普通配置只保留引用", () => {
  const html = render({
    ...props,
    plugin: "community.synthetic",
    schema: {
      type: "object",
      properties: {
        api_key: { type: "string", format: "credential-ref", title: "API Key" },
      },
    },
    credentialFields: { api_key: { title: "API Key", purpose: "ocr.auth" } },
    value: { api_key: "cred." + "a".repeat(32) },
    provenance: {},
    onSaveCredential: async () => "cred." + "b".repeat(32),
  });
  assert.match(html, /type="password"/);
  assert.match(html, /autoComplete="new-password"/);
  assert.match(html, /已配置凭据/);
  assert.ok(!html.includes('value="cred.'));
});

test("OCR 表单显示十个数值控件和一个开关，JSON 默认折叠且无重复来源列表", () => {
  const html = render(props);
  assert.equal((html.match(/type="number"/g) ?? []).length, 10);
  assert.equal((html.match(/type="checkbox"/g) ?? []).length, 1);
  assert.equal((html.match(/class="plugin-config-meta"/g) ?? []).length, 11);
  for (const field of fields)
    assert.ok(html.includes(field.label), field.label);
  assert.match(
    html,
    /<details class="plugin-config-json"><summary>高级 JSON<\/summary>/,
  );
  assert.ok(html.includes("1–16"));
  assert.ok(html.includes("全部重置"));
  assert.ok(!html.includes("来源："));
  assert.ok(!html.includes("恢复继承"));
  assert.ok(!html.includes("JSON 会替换"));
});

test("重置预览显示后端返回的继承值及来源，计划期间所有编辑控件冻结", () => {
  const draft = resetConfigField(emptyConfigDraft(), threads.path);
  const pending = render({
    ...props,
    value: { ...props.value, intra_op_num_threads: 8 },
    draft,
  });
  assert.ok(pending.includes("待恢复"));
  assert.ok(pending.includes("撤销重置"));
  assert.equal((pending.match(/type="number"/g) ?? []).length, 9);
  const preview = render({
    ...props,
    draft,
    disabled: true,
    preview: {
      value: { ...props.value, intra_op_num_threads: 6 },
      provenance: { ...props.provenance, [threads.pointer]: "bundle:local" },
    },
  });
  assert.ok(preview.includes('value="6"'));
  assert.ok(preview.includes("配置文件 · local"));
  assert.ok(!preview.includes("待恢复"));
  for (const control of preview.matchAll(
    /<(?:input|select|textarea|button)\b[^>]*>/g,
  ))
    assert.ok(control[0].includes('disabled=""'), control[0]);
});

test("未完成字段保留输入、错误及可用的全部重置操作", () => {
  const draft = changeConfigField(emptyConfigDraft(), threads, { text: "" });
  const html = render({ ...props, draft });
  assert.match(html, /aria-invalid="true"[^>]*value=""/);
  assert.ok(html.includes("请输入数值"));
  assert.match(html, /<button type="button">全部重置<\/button>/);
  const raw = render({ ...props, draft: changeConfigJson("{") });
  assert.ok(raw.includes("JSON 配置无效"));
  assert.equal((raw.match(/<input[^>]*disabled=""/g) ?? []).length, 11);
  assert.match(raw, /<textarea[^>]*aria-invalid="true"[^>]*>\{<\/textarea>/);
});

test("枚举、字符串、空值及复杂类型各自使用独立控件", () => {
  const html = render({
    ...props,
    title: "扩展",
    schema: {
      properties: {
        name: { type: "string", title: "名称" },
        mode: { enum: [false, 0, "", null], title: "模式" },
        optional: { type: ["number", "null"], title: "可选数值" },
        extra: { type: "array", title: "扩展数组" },
      },
    },
    value: { name: "", mode: null, optional: null, extra: [1] },
  });
  assert.ok(html.includes('type="text"'));
  assert.ok(html.includes('<option value="null" selected="">空值</option>'));
  assert.ok(html.includes('class="plugin-config-null"'));
  assert.equal((html.match(/<textarea/g) ?? []).length, 2);
  assert.ok(!html.includes('value="undefined"'));
});
