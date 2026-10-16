import assert from "node:assert/strict";
import { test } from "node:test";
import { buildSync } from "esbuild";
import { fileURLToPath } from "node:url";

const external = ["react", "react-dom/server", "react/jsx-runtime"];
let source = buildSync({
  stdin: {
    contents: `import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import ImporterSelect from "./src/shared/components/ImporterSelect";
      export function render(value, disabled) { return renderToStaticMarkup(createElement(ImporterSelect, { value, disabled })); }`,
    resolveDir: fileURLToPath(new URL("../", import.meta.url)),
  },
  bundle: true,
  platform: "node",
  format: "esm",
  jsx: "automatic",
  external,
  write: false,
}).outputFiles[0].text;
for (const name of external)
  source = source.replaceAll(
    JSON.stringify(name),
    JSON.stringify(import.meta.resolve(name)),
  );
const { render } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

/** 构造可选择的两项合成处理器，不依赖宿主或文件内容 */
function fixture() {
  return {
    items: [
      {
        id: "community.first/image",
        title: "合成图片",
        owner: "community.first",
      },
      {
        id: "community.second/image",
        title: "另一图片",
        owner: "community.second",
      },
    ],
    selected: "",
    missing: false,
    loading: false,
    conflict: "",
    error: "",
    extensions: [".png"],
    setSelected() {},
  };
}

test("import defaults to automatic recognition and keeps technical choices collapsed", () => {
  const html = render(fixture());
  assert.match(html, /文件处理：自动识别/);
  assert.match(html, /<details class="importer-advanced">/);
  assert.doesNotMatch(html.split("<details")[0], /community\./);
});

test("explicit old selection, missing importer and real conflicts remain visible", () => {
  const value = fixture();
  value.selected = "community.second/image";
  let html = render(value);
  assert.match(html, /value="community.second\/image" selected/);
  assert.match(html, /<details class="importer-advanced" open="">/);
  value.missing = true;
  value.items = [];
  html = render(value);
  assert.match(html, /所选处理器已不可用/);
  assert.match(html, /value="community.second\/image" selected/);
  const conflict = {
    ...fixture(),
    conflict: "多个处理器可以处理此文件，请明确选择后重试。",
  };
  html = render(conflict, true);
  assert.match(html, /<details class="importer-advanced" open="">/);
  assert.match(html, /<select disabled="">/);
  assert.match(html, /请明确选择后重试/);
});
