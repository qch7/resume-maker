import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

/** 运行真实日志设置组件，替换浏览器 hooks 和网络以验证两项开关的保存 */
async function application() {
  const frontend = fileURLToPath(new URL("../", import.meta.url));
  const result = await build({
    stdin: {
      contents: `export {default as Settings} from "../src/resume_maker/plugin_packages/sys_resume/client/features/settings/ActivitySettings";
        export {begin, flushEffects} from "react"; export * from "fixture/api";`,
      resolveDir: frontend,
    },
    bundle: true,
    format: "esm",
    platform: "browser",
    jsx: "automatic",
    write: false,
    plugins: [
      {
        name: "activity-settings-fixtures",
        setup(builder) {
          builder.onResolve({ filter: /^(react|react\/jsx-runtime)$/ }, () => ({
            path: "react",
            namespace: "fixture",
          }));
          builder.onResolve(
            { filter: /^fixture\/api$|^@resume-maker\/plugin-sdk\// },
            (args) => {
              if (args.path.endsWith("/plugins/activity"))
                return { path: frontend + "src/plugins/activity.ts" };
              if (args.path.endsWith("/activityPreferences"))
                return {
                  path: frontend + "src/shared/lib/activityPreferences.ts",
                };
              return {
                path: args.path.endsWith("/localTime") ? "time" : "api",
                namespace: "fixture",
              };
            },
          );
          builder.onLoad({ filter: /.*/, namespace: "fixture" }, (args) => ({
            loader: "js",
            contents:
              args.path === "react"
                ? `let values = [], index = 0, effects = [], seen = new Set();
            export function begin() {index = 0;}
            export function useState(initial) {
              const key = index++;
              if (!(key in values)) values[key] = initial;
              return [values[key], next => values[key] = typeof next === "function" ? next(values[key]) : next];
            }
            export function useEffect(effect) {const key = index++; if (!seen.has(key)) {seen.add(key); effects.push(effect);}}
            export async function flushEffects() {for (const effect of effects.splice(0)) effect(); await new Promise(resolve => setTimeout(resolve, 0));}
            export function jsx(type, props) {return {type, props};} export const jsxs = jsx;`
                : args.path === "time"
                  ? "export const localDayRange = () => ({since: '2026-10-10T00:00:00+08:00'});"
                  : `export const requests = []; export let failSave = false; export function rejectSave(value) {failSave = value;}
              export async function api(path, method = "GET", body) {
                requests.push({path, method, body});
                if (method === "GET") return {categories: ["ai"], capture_starts: false};
                if (failSave) throw new Error("synthetic save failure");
                return body;
              }`,
          }));
        },
      },
    ],
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`
  );
}

/** 收集组件节点，保留 label 和按钮以模拟用户直接操作 */
function nodes(node) {
  if (Array.isArray(node)) return node.flatMap(nodes);
  if (!node || typeof node !== "object") return [];
  return [node, ...nodes(node.props?.children)];
}

/** 按界面文案取得勾选框，不依赖控件顺序 */
function checkbox(tree, title) {
  const label = nodes(tree).find(
    (node) => node.type === "label" && node.props.children?.includes(title),
  );
  return nodes(label).find((node) => node.type === "input");
}

/** 按已有按钮文案触发设置操作 */
function button(tree, title) {
  return nodes(tree).find(
    (node) => node.type === "button" && node.props.children === title,
  );
}

test("采集和显示开始事件独立保存，类别操作保留选择，恢复默认关闭两项", async () => {
  const app = await application();
  const saved = [];
  const props = {
    rules: "/api/custom",
    defaultRules: "/api/state",
    showStarts: false,
    onSave: (...args) => saved.push(args),
    onResetLayout() {},
    onDeleted() {},
  };
  const render = () => {
    app.begin();
    return app.Settings(props);
  };
  let tree = render();
  await app.flushEffects();
  tree = render();
  assert.equal(checkbox(tree, "采集开始事件").props.checked, false);
  assert.equal(checkbox(tree, "显示开始事件").props.checked, false);
  checkbox(tree, "采集开始事件").props.onChange({ target: { checked: true } });
  tree = render();
  checkbox(tree, "工具").props.onChange({ target: { checked: true } });
  tree = render();
  assert.equal(checkbox(tree, "采集开始事件").props.checked, true);
  button(tree, "全选").props.onClick();
  tree = render();
  button(tree, "仅 AI 消息").props.onClick();
  tree = render();
  assert.equal(checkbox(tree, "采集开始事件").props.checked, true);
  button(tree, "保存").props.onClick();
  await app.flushEffects();
  assert.deepEqual(app.requests.at(-1).body, {
    categories: ["ai"],
    capture_starts: true,
  });
  assert.deepEqual(saved.at(-1), ["/api/custom", false]);
  tree = render();
  checkbox(tree, "显示开始事件").props.onChange({ target: { checked: true } });
  tree = render();
  app.rejectSave(true);
  button(tree, "保存").props.onClick();
  await app.flushEffects();
  assert.equal(saved.length, 1);
  tree = render();
  assert.equal(checkbox(tree, "显示开始事件").props.checked, true);
  app.rejectSave(false);
  checkbox(tree, "采集开始事件").props.onChange({ target: { checked: false } });
  tree = render();
  button(tree, "保存").props.onClick();
  await app.flushEffects();
  assert.deepEqual(saved.at(-1), ["/api/custom", true]);
  assert.equal(app.requests.at(-1).body.capture_starts, false);
  tree = render();
  button(tree, "恢复默认").props.onClick();
  tree = render();
  assert.equal(checkbox(tree, "采集开始事件").props.checked, false);
  assert.equal(checkbox(tree, "显示开始事件").props.checked, false);
  button(tree, "保存").props.onClick();
  await app.flushEffects();
  assert.deepEqual(app.requests.at(-1).body, {
    categories: ["ai"],
    capture_starts: false,
  });
  assert.deepEqual(saved.at(-1), ["/api/state", false]);
});
