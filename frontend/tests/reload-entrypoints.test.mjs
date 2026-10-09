import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

/** 保留实际组件及协调器，只提供不依赖浏览器渲染器的 hooks 和页面节点 */
async function application() {
  const fixtures = {
    react: `let values = [], index = 0;
      export function begin() { index = 0; }
      export function useState(initial) {
        const key = index++;
        if (!(key in values)) values[key] = initial;
        return [values[key], value => values[key] = typeof value === "function" ? value(values[key]) : value];
      }
      export function useEffect() {}
      export function useSyncExternalStore(_subscribe, snapshot) { return snapshot(); }
      export function jsx(type, props) { return { type, props }; }
      export const jsxs = jsx, Fragment = "fragment";`,
    "react-dom": "export function createPortal(node) { return node; }",
    runtime: `export const clientFailures = [];
      export function pluginPages() { return []; }
      export function pluginComponent() { return () => null; }`,
    storage: `export const events = [];
      export const storage = {
        issues: () => [{key: "draft", conflict: true, error: "conflict"}],
        recoveries: () => [], pending: () => false,
        resolve: async () => { events.push("resolve"); },
        prepareReload: async () => { events.push("preserve"); }
      };
      export const storageVersion = () => 0, subscribeStorage = () => () => {};`,
    component: "export default function Component() { return null; }",
  };
  const result = await build({
    stdin: {
      contents: `export {default as App} from "../src/resume_maker/plugin_packages/sys_workbench/client/App";
        export {default as PersistenceStatus} from "./src/shared/components/PersistenceStatus";
        export * from "./src/plugins/window";
        export {clientExtensions} from "./src/plugins/extensions";
        export {setCapabilities} from "./src/shared/lib/capabilities";
        export {registerDraft} from "./src/shared/lib/draftRegistry";
        export {begin} from "react";
        export {events} from "fixture/storage";`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    alias: {
      "@resume-maker/plugin-sdk": fileURLToPath(
        new URL("../src/plugins/shared/exports", import.meta.url),
      ),
    },
    bundle: true,
    platform: "browser",
    format: "esm",
    jsx: "automatic",
    write: false,
    plugins: [
      {
        name: "render-fixtures",
        setup(builder) {
          builder.onResolve(
            { filter: /^(react|react\/jsx-runtime|react-dom)$/ },
            ({ path }) => ({
              path: path === "react/jsx-runtime" ? "react" : path,
              namespace: "fixture",
            }),
          );
          builder.onResolve(
            { filter: /(?:plugins\/runtime|lib\/storage|fixture\/storage)$/ },
            ({ path }) => ({
              path: path.endsWith("runtime") ? "runtime" : "storage",
              namespace: "fixture",
            }),
          );
          builder.onResolve(
            { filter: /(?:PluginManager|CommandMenu|PluginBoundary)$/ },
            () => ({
              path: "component",
              namespace: "fixture",
            }),
          );
          builder.onLoad(
            { filter: /.*/, namespace: "fixture" },
            ({ path }) => ({
              contents: fixtures[path],
              loader: "js",
            }),
          );
        },
      },
    ],
  });
  const module = await import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}#${crypto.randomUUID()}`
  );
  module.setCapabilities({
    generation: 7,
    host_api: "1.0.0",
    client_api: "1.0.0",
    ready: true,
    plugins: [],
    services: [],
    client: [],
    sandbox: {},
  });
  return module;
}

/** 从实际组件返回的节点中找到可点击的入口 */
function button(tree, title) {
  const nodes = Array.isArray(tree) ? tree : [tree];
  for (const node of nodes) {
    if (!node?.props) continue;
    if (node.type === "button" && node.props.children === title) return node;
    const found = button(node.props.children, title);
    if (found) return found;
  }
}

for (const [component, title] of [
  ["App", "重新协商并加载"],
  ["PersistenceStatus", "载入已保存内容"],
]) {
  test(`${title}在排空超时后仍等待命令结束，重试才保存并刷新`, async (t) => {
    const documentBefore = globalThis.document,
      locationBefore = globalThis.location;
    let reloads = 0,
      finish,
      signal;
    globalThis.document = {
      body: {},
      querySelector: () => ({ content: "synthetic" }),
    };
    globalThis.location = {
      reload: () => {
        reloads++;
      },
    };
    t.mock.method(globalThis, "fetch", async (url) => {
      if (url === "/api/plugins/windows")
        return Response.json({ pending_plan: "change", acknowledged: false });
      if (url === "/api/plugins/plans/change")
        return Response.json({ affected: [], generation: 7 });
      throw new Error(`未结束的命令不能确认：${url}`);
    });
    const module = await application();
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const id = "community.wait/run";
    const dispose = module.clientExtensions.contribute(
      {
        id: "community.wait",
        entry: { mode: "trusted-client", entry: "index.js" },
        contributes: { commands: [id] },
      },
      "commands",
      id,
      {
        title: "wait",
        run(context) {
          signal = context.signal;
          return new Promise((resolve) => {
            finish = resolve;
          });
        },
      },
    );
    const pending = module.clientExtensions.execute(id);
    const drafts = [];
    let finished = false;
    const unregister = module.registerDraft("final-input", async () => {
      drafts.push(finished ? "final" : "initial");
    });
    try {
      await Promise.resolve();
      const preparing = module.connectWindow();
      await new Promise(setImmediate);
      t.mock.timers.tick(5000);
      await preparing;
      assert.equal(signal.aborted, true);
      assert.match(module.windowNotice(), /未结束/);
      module.begin();
      const entry = button(module[component](), title);
      assert.ok(entry);
      entry.props.onClick();
      await new Promise(setImmediate);
      t.mock.timers.tick(5000);
      await new Promise(setImmediate);
      assert.equal(reloads, 0);
      assert.deepEqual(module.events, []);
      assert.deepEqual(drafts, ["initial"]);
      finish();
      await pending;
      finished = true;
      entry.props.onClick();
      await new Promise(setImmediate);
      assert.equal(reloads, 1);
      assert.deepEqual(
        drafts,
        component === "App" ? ["initial", "final"] : ["initial"],
      );
      assert.deepEqual(
        module.events,
        component === "PersistenceStatus" ? ["resolve", "preserve"] : [],
      );
    } finally {
      finish();
      await pending;
      await dispose();
      unregister();
      globalThis.document = documentBefore;
      globalThis.location = locationBefore;
    }
  });
}
