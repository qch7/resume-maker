import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

/** 编译实际设置和插件面板，只替换浏览器 hooks、网络及无关子组件 */
async function application() {
  const fixtures = {
    react: `let values = [], index = 0, effects = [], cleanups = [];
      export function begin() { index = 0; }
      export function useState(initial) {
        const key = index++;
        if (!(key in values)) values[key] = typeof initial === "function" ? initial() : initial;
        return [values[key], next => values[key] = typeof next === "function" ? next(values[key]) : next];
      }
      export function useRef(initial) { const key = index++; return values[key] ??= {current: initial}; }
      export function useCallback(value) { return value; }
      export function useEffect(effect, dependencies) {
        const key = index++, previous = values[key];
        if (!previous || dependencies.some((value, i) => value !== previous[i])) {
          values[key] = dependencies;
          effects.push(() => { cleanups[key]?.(); cleanups[key] = effect(); });
        }
      }
      export function flushEffects() { for (const effect of effects.splice(0)) effect(); }
      export function dispose() { for (const cleanup of cleanups) cleanup?.(); }
      export function jsx(type, props) { return {type, props}; }
      export const jsxs = jsx, Fragment = "fragment";`,
    state: `export const requests = [], guards = [];
      export let pages = [], failAbort = false;
      export function setPages(value) { pages = value; }
      export function rejectAbort(value) { failAbort = value; }
      export const pluginSettingsPages = () => pages;
      export const capabilities = () => ({generation: 7});
      export const hasPlugin = () => true;
      export async function api(path, method = "GET", body) {
        requests.push({path, method, body});
        if (path === "/settings") return {data_dir: "synthetic"};
        if (path === "/plugins") return {
          profiles: {minimal: ["sys.core"], standard: ["sys.core", "ext.extra"]},
          instances: [], pins: {}, packages: {}, task_persistence_errors: [],
          plugins: [
            {id: "sys.core", title: "基础", required: true, enabled: true, state: "就绪", version: "1.0", builtin: true, requires: {}},
            {id: "ext.extra", title: "扩展", required: false, enabled: false, state: "停用", version: "1.0", builtin: true, requires: {}}
          ]
        };
        if (path === "/plugins/operations") return [];
        if (path === "/plugins/plans" && method === "POST") return {
          id: "change", digest: "verified", state: "planned", mode: "hot",
          added: body.selected.filter(id => id === "ext.extra"), removed: [], affected: body.selected
        };
        if (path.endsWith("/abort")) {
          if (failAbort) throw new Error("撤销失败");
          return {};
        }
        throw new Error("Unexpected request " + path);
      }
      export async function connectWindow() { requests.push({path: "connect"}); }
      export async function reloadWindow() { requests.push({path: "reload"}); }
      export const DEFAULT_ACTIVITY_PREFERENCES = {};
      export async function download() {}
      export function registerBeforeClose(guard) { guards.push(guard); return () => guards.splice(guards.indexOf(guard), 1); }
      export function Icon() {return null;}
      export const DatabaseBackup = Icon, FolderOpen = Icon, ScrollText = Icon, ShieldCheck = Icon,
        SlidersHorizontal = Icon, X = Icon, ChevronDown = Icon, Puzzle = Icon, Search = Icon;
      export function Component() { return null; }
      export default Component;`,
  };
  const output = await build({
    stdin: {
      contents: `export {default as Settings} from "../src/resume_maker/plugin_packages/sys_resume/client/features/settings/Settings";
        export {default as PluginManager} from "../src/resume_maker/plugin_packages/sys_workbench/client/features/plugins/PluginManager";
        export * from "fixture/state"; export {begin, flushEffects, dispose} from "react";`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    platform: "browser",
    format: "esm",
    jsx: "automatic",
    write: false,
    plugins: [
      {
        name: "settings-fixtures",
        setup(builder) {
          builder.onResolve({ filter: /^(react|react\/jsx-runtime)$/ }, () => ({
            path: "react",
            namespace: "fixture",
          }));
          builder.onResolve(
            {
              filter:
                /^(fixture\/state|lucide-react|@resume-maker\/plugin-sdk\/)/,
            },
            () => ({ path: "state", namespace: "fixture" }),
          );
          builder.onResolve(
            { filter: /^\.\/(Privacy|ActivitySettings|PackageDownloads)$/ },
            () => ({ path: "state", namespace: "fixture" }),
          );
          builder.onLoad(
            { filter: /.*/, namespace: "fixture" },
            ({ path }) => ({ contents: fixtures[path], loader: "js" }),
          );
        },
      },
    ],
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(output.outputFiles[0].text).toString("base64")}#${crypto.randomUUID()}`
  );
}

/** 从组件返回的树中查找符合条件的实际控件 */
function nodes(tree, match) {
  return (Array.isArray(tree) ? tree : [tree]).flatMap((node) => {
    if (Array.isArray(node)) return nodes(node, match);
    if (!node?.props) return [];
    return [
      ...(match(node) ? [node] : []),
      ...nodes(node.props.children, match),
    ];
  });
}

/** 重新执行组件并处理本轮 hooks */
function render(module, component, props) {
  module.begin();
  const tree = module[component](props);
  module.flushEffects();
  return tree;
}

/** 等待异步按钮操作完成当前请求及状态更新 */
async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
}

test("项目创建和扫描共用分类，切换后保留输入且命令可打开已有设置中的插件页", async () => {
  const module = await application();
  module.setPages([
    {
      id: "source/scan",
      title: "扫描导入",
      group: "projects",
      openFor: ["projects"],
      order: 5,
      component: module.Component,
    },
    {
      id: "workbench/plugins",
      title: "插件",
      openFor: ["plugins"],
      order: 30,
      component: module.Component,
    },
  ]);
  const props = {
    initial: "projects",
    activityPreferences: { preferences: {}, setPreferences() {} },
    run: (work) => work(),
    onChanged: async () => {},
    onClose() {},
  };
  let tree = render(module, "Settings", props);
  const navigation = nodes(tree, (node) => node.type === "nav")[0];
  assert.equal(nodes(navigation, (node) => node.type === "button").length, 5);
  assert.equal(
    nodes(tree, (node) => node.type === module.Component && node.props.active)
      .length,
    1,
  );
  nodes(tree, (node) => node.type === "input")[0].props.onChange({
    target: { value: "保留项目" },
  });
  nodes(
    navigation,
    (node) =>
      node.props["aria-current"] === undefined && node.type === "button",
  )[0].props.onClick();
  render(module, "Settings", props);
  tree = render(module, "Settings", { ...props, initial: "plugins" });
  tree = render(module, "Settings", { ...props, initial: "plugins" });
  assert.equal(
    nodes(tree, (node) => node.type === module.Component && node.props.active)
      .length,
    1,
  );
  assert.equal(
    nodes(tree, (node) => node.type === "input")[0].props.value,
    "保留项目",
  );
  module.dispose();
});

test("设置关闭收尾失败时保留窗口，重复点击共用一次收尾并允许重试", async () => {
  const module = await application();
  module.setPages([
    {
      id: "workbench/plugins",
      title: "插件",
      openFor: ["plugins"],
      order: 30,
      component: module.Component,
    },
  ]);
  let closed = 0,
    release;
  const props = {
    initial: "plugins",
    activityPreferences: { preferences: {}, setPreferences() {} },
    onClose: () => closed++,
  };
  let tree = render(module, "Settings", props);
  const panel = nodes(
    tree,
    (node) => node.type === module.Component && node.props.registerBeforeClose,
  )[0];
  const unregister = panel.props.registerBeforeClose(
    () =>
      new Promise((_resolve, reject) => {
        release = reject;
      }),
  );
  const close = nodes(
    tree,
    (node) => node.props["aria-label"] === "关闭设置",
  )[0];
  close.props.onClick();
  close.props.onClick();
  release(new Error("撤销失败"));
  await settle();
  tree = render(module, "Settings", props);
  assert.equal(closed, 0);
  assert.equal(
    nodes(tree, (node) => node.props.role === "alert")[0].props.children,
    "撤销失败",
  );
  unregister();
  nodes(
    tree,
    (node) => node.props["aria-label"] === "关闭设置",
  )[0].props.onClick();
  await settle();
  assert.equal(closed, 1);
  module.dispose();
});

test("模式选择只暂存候选，查看变更才发送包含配置代次的完整组合", async () => {
  const module = await application();
  const props = { registerBeforeClose: module.registerBeforeClose };
  render(module, "PluginManager", props);
  await settle();
  let tree = render(module, "PluginManager", props);
  const mode = nodes(
    tree,
    (node) => node.props["aria-label"] === "插件模式",
  )[0];
  assert.equal(mode.props.value, "minimal");
  mode.props.onChange({ target: { value: "extended" } });
  tree = render(module, "PluginManager", props);
  assert.equal(
    module.requests.filter((request) => request.method === "POST").length,
    0,
  );
  assert.equal(
    nodes(
      tree,
      (node) => node.props.role === "switch" && node.props.disabled,
    )[0].props["aria-checked"],
    true,
  );
  nodes(
    tree,
    (node) => node.type === "button" && node.props.children === "查看变更",
  )[0].props.onClick();
  await settle();
  assert.deepEqual(
    module.requests.find((request) => request.path === "/plugins/plans").body
      .selected,
    ["sys.core", "ext.extra"],
  );
  assert.equal(
    module.requests.find((request) => request.path === "/plugins/plans").body
      .generation,
    7,
  );
  module.dispose();
});

test("插件页关闭使用最新计划摘要，撤销失败可重试且成功后解除窗口冻结", async () => {
  const module = await application();
  const props = { registerBeforeClose: module.registerBeforeClose };
  render(module, "PluginManager", props);
  await settle();
  let tree = render(module, "PluginManager", props);
  nodes(
    tree,
    (node) => node.type === "button" && node.props.children === "查看变更",
  )[0].props.onClick();
  await settle();
  render(module, "PluginManager", props);
  module.rejectAbort(true);
  await assert.rejects(module.guards[0](), /撤销失败/);
  assert.equal(
    module.requests.some((request) => request.path === "connect"),
    false,
  );
  module.rejectAbort(false);
  await module.guards[0]();
  assert.deepEqual(
    module.requests
      .filter((request) => request.path.endsWith("/abort"))
      .map((request) => request.body),
    [{ digest: "verified" }, { digest: "verified" }],
  );
  assert.equal(module.requests.at(-1).path, "connect");
  module.dispose();
});
