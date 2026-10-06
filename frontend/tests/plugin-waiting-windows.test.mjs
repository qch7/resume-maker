import assert from "node:assert/strict";
import test from "node:test";
import { buildSync } from "esbuild";
import { fileURLToPath } from "node:url";

/** 渲染实际窗口列表，检查用户能辨认的名称及操作说明 */
async function waitingWindows() {
  const output = buildSync({
    stdin: {
      contents: `import { renderToStaticMarkup } from "react-dom/server";
        import WaitingWindows from "../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/WaitingWindows";
        export { windowId } from "./src/plugins/window";
        export function render(props) { return renderToStaticMarkup(WaitingWindows(props)); }`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    platform: "node",
    format: "esm",
    jsx: "automatic",
    tsconfigRaw: {},
    external: ["react-dom/server", "react/jsx-runtime"],
    alias: {
      "@resume-maker/plugin-sdk/plugins/window": fileURLToPath(
        new URL("../src/plugins/window.ts", import.meta.url),
      ),
    },
    write: false,
  }).outputFiles[0].text;
  // 临时模块使用绝对包地址，data URL 没有相对包解析上下文
  const source = output
    .replaceAll(
      '"react-dom/server"',
      JSON.stringify(import.meta.resolve("react-dom/server")),
    )
    .replaceAll(
      '"react/jsx-runtime"',
      JSON.stringify(import.meta.resolve("react/jsx-runtime")),
    );
  const previous = globalThis.document;
  globalThis.document = { querySelector: () => ({ content: "synthetic" }) };
  try {
    return await import(
      `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
    );
  } finally {
    globalThis.document = previous;
  }
}

test("在线、当前及离线窗口显示页面名称和各自处理方式，不暴露内部编号", async () => {
  const module = await waitingWindows();
  const online = "internal-online-uuid",
    offline = "internal-offline-uuid";
  const now = Date.now() / 1000;
  const html = module.render({
    ids: [module.windowId, online, offline],
    details: {
      [module.windowId]: {
        number: 1,
        title: "ResumeMaker · 当前项目",
        connected: true,
        last_seen: now,
      },
      [online]: {
        number: 2,
        title: "ResumeMaker · 另一个项目",
        status: "草稿版本冲突",
        connected: true,
        last_seen: now,
      },
      [offline]: {
        number: 3,
        title: "ResumeMaker · 模板库",
        connected: false,
        last_seen: now,
      },
    },
    busy: false,
  });
  for (const phrase of [
    "当前窗口",
    "当前项目",
    "窗口 2",
    "另一个项目",
    "草稿版本冲突",
    "定位窗口",
    "窗口 3",
    "模板库",
    "已关闭或暂时离线",
    "保留恢复副本并继续",
    "最后响应",
  ])
    assert.ok(html.includes(phrase), phrase);
  for (const id of [online, offline, module.windowId])
    assert.ok(!html.includes(id));
});

test("过期心跳及未记录名称的旧窗口提供离线恢复说明", async () => {
  const module = await waitingWindows();
  const html = module.render({
    ids: ["stale", "old"],
    details: {
      stale: {
        number: 4,
        title: "失联页面",
        connected: true,
        last_seen: Date.now() / 1000 - 20,
      },
    },
    busy: true,
  });
  assert.ok(html.includes("窗口 4"));
  assert.ok(html.includes("未记录页面名称的旧窗口"));
  assert.ok(html.includes("旧输入以后需核对恢复"));
  assert.equal(html.includes("定位窗口"), false);
  assert.equal((html.match(/disabled=""/g) ?? []).length, 2);
});
