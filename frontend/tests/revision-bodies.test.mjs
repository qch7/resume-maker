import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import { orderCompositionHighlights } from "../src/shared/resume/composition.ts";

/** 运行实际正文钩子，用可控依赖比较、网络替身复现慢读取期间的连续重渲染 */
async function application() {
  const fixtures = {
    react: `let values = [], index = 0, effects = [], cleanups = [];
      export function begin() { index = 0; }
      export function useRef(initial) { const key = index++; return values[key] ??= {current: initial}; }
      export function useEffect(effect, dependencies) {
        const key = index++, previous = values[key];
        if (!previous || dependencies.some((value, i) => !Object.is(value, previous[i]))) {
          values[key] = dependencies;
          effects.push(() => { cleanups[key]?.(); cleanups[key] = effect(); });
        }
      }
      export function flushEffects() { for (const effect of effects.splice(0)) effect(); }
      export function dispose() { for (const cleanup of cleanups) cleanup?.(); }`,
    api: `export const requests = [];
      export function api(path, method, body, signal) {
        return new Promise((resolve, reject) => requests.push({path, signal, resolve, reject}));
      }`,
  };
  const output = await build({
    stdin: {
      contents: `export {useRevisionBodies} from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/useRevisionBodies";
        export {begin, flushEffects, dispose} from "react";
        export {requests} from "@resume-maker/plugin-sdk/shared/lib/api";`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    platform: "browser",
    format: "esm",
    write: false,
    plugins: [
      {
        name: "revision-body-fixtures",
        setup(builder) {
          builder.onResolve(
            { filter: /^(react|@resume-maker\/plugin-sdk\/shared\/lib\/api)$/ },
            ({ path }) => ({
              path: path === "react" ? "react" : "api",
              namespace: "fixture",
            }),
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

/** 执行一轮渲染及提交后副作用，沿用 React 按依赖清理旧请求的顺序 */
function render(module, items, cache, receive, onError = assert.fail) {
  module.begin();
  module.useRevisionBodies(items, cache, receive, onError);
  module.flushEffects();
}

/** 等待请求回填、错误处理结束当前微任务 */
async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
}

test("慢正文读取不会被持续编辑、条目重排或其他版本入缓存打断", async () => {
  const module = await application();
  let cache = { a: { id: "a", content: { highlights: [] } } };
  const items = ["b", "a", "b"].map((revision_id) => ({
    revision_id,
    highlight_ids: [],
  }));
  render(module, items, cache, (update) => {
    cache = update(cache);
  });
  for (let index = 0; index < 6; index++) {
    cache = {
      ...cache,
      [`other${index}`]: { id: `other${index}`, content: { highlights: [] } },
    };
    const draft = orderCompositionHighlights(
      {
        name: `编辑 ${index}`,
        items: [...items].reverse().map((item) => ({ ...item })),
      },
      cache,
    );
    assert.notEqual(draft.items, items);
    render(module, draft.items, cache, (update) => {
      cache = update(cache);
    });
  }
  assert.equal(module.requests.length, 1);
  assert.equal(module.requests[0].path, "/revisions/b");
  assert.equal(module.requests[0].signal.aborted, false);
  module.requests[0].resolve({
    id: "b",
    content: { title: "正文", highlights: [] },
  });
  await settle();
  assert.equal(cache.b.content.title, "正文");
  assert.ok(cache.other5);
  render(module, items, cache, (update) => {
    cache = update(cache);
  });
  assert.equal(module.requests.length, 1);
  module.dispose();
});

test("引用集合改变、卸载会取消请求并阻止旧正文回填", async () => {
  const module = await application();
  let cache = {};
  const errors = [];
  render(
    module,
    [{ revision_id: "old" }],
    cache,
    (update) => {
      cache = update(cache);
    },
    (error) => errors.push(error),
  );
  const old = module.requests[0];
  render(
    module,
    [{ revision_id: "new" }],
    cache,
    (update) => {
      cache = update(cache);
    },
    (error) => errors.push(error),
  );
  assert.equal(old.signal.aborted, true);
  assert.equal(module.requests[1].path, "/revisions/new");
  old.resolve({ id: "old" });
  module.requests[1].resolve({ id: "new" });
  await settle();
  assert.deepEqual(cache, { new: { id: "new" } });
  render(
    module,
    [{ revision_id: "closing" }],
    cache,
    (update) => {
      cache = update(cache);
    },
    (error) => errors.push(error),
  );
  module.dispose();
  assert.equal(module.requests[2].signal.aborted, true);
  module.requests[2].reject(new Error("关闭后失败"));
  await settle();
  assert.deepEqual(errors, []);
  assert.deepEqual(cache, { new: { id: "new" } });
});

test("新增引用从最新缓存补齐，取消后尚未应用的状态更新也失效", async () => {
  const module = await application();
  const cache = { cached: { id: "cached" } };
  const updates = [];
  render(module, [{ revision_id: "pending" }], cache, (update) =>
    updates.push(update),
  );
  module.requests[0].resolve({ id: "pending" });
  await settle();
  render(module, [{ revision_id: "cached" }], cache, (update) =>
    updates.push(update),
  );
  assert.equal(module.requests.length, 1);
  assert.equal(updates[0](cache), cache);
  module.dispose();
});
