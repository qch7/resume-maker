import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_LOCATION,
  normalizeWorkspaceLocation,
  readWorkspaceLocation,
  workspaceScrollKey,
  workspaceUrl,
} from "../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/workspaceLocation.ts";

/** 构造独立项目、会话，验证失效引用不会串到其他项目 */
function state() {
  return {
    projects: [
      { id: "p", head_revision: "r1" },
      { id: "other", head_revision: "r2" },
    ],
    conversations: [
      { id: "chat", project_id: "p" },
      { id: "other-chat", project_id: "other" },
    ],
    branches: [],
  };
}

test("地址优先恢复位置，往返保留独立参数且不包含正文资料", () => {
  const saved = { ...DEFAULT_LOCATION, area: "personal", projectId: "p" };
  assert.deepEqual(readWorkspaceLocation("http://local/", saved), saved);
  const selected = {
    ...saved,
    area: "projects",
    mode: "chat",
    conversationId: "chat",
    revisionId: "历史/版本",
  };
  const url = workspaceUrl("http://local/?keep=yes#anchor", selected);
  assert.match(url, /keep=yes/);
  assert.match(url, /#anchor$/);
  assert.deepEqual(
    readWorkspaceLocation(new URL(url, "http://local").href, saved),
    selected,
  );
  assert.equal(
    readWorkspaceLocation("http://local/?workspace=structure", saved).area,
    "structure",
  );
  assert.equal(
    readWorkspaceLocation("http://local/?workspace=structure", saved).projectId,
    "",
  );
  assert.deepEqual(
    readWorkspaceLocation("http://local/", { projectId: 4, mode: "invalid" }),
    DEFAULT_LOCATION,
  );
});

test("缺失插件、项目、会话回到有效位置，拒绝跨项目会话且不改资料", () => {
  const data = state();
  const before = structuredClone(data);
  const result = normalizeWorkspaceLocation(
    {
      ...DEFAULT_LOCATION,
      area: "templates",
      page: "missing",
      projectId: "deleted",
      mode: "chat",
      conversationId: "other-chat",
      revisionId: "old",
    },
    data,
    ["projects", "personal", "structure"],
    [],
    false,
    "p",
  );
  assert.deepEqual(result, {
    ...DEFAULT_LOCATION,
    projectId: "p",
    revisionId: "r1",
  });
  const chat = normalizeWorkspaceLocation(
    {
      ...DEFAULT_LOCATION,
      projectId: "p",
      mode: "chat",
      conversationId: "other-chat",
    },
    data,
    ["projects"],
    [],
    true,
    "p",
  );
  assert.equal(chat.conversationId, "chat");
  assert.deepEqual(data, before);
});

test("保存新版本沿用滚动位置，不同项目及会话独立恢复", () => {
  const location = { ...DEFAULT_LOCATION, projectId: "p", revisionId: "r1" };
  assert.equal(
    workspaceScrollKey(location),
    workspaceScrollKey({ ...location, revisionId: "r2" }),
  );
  assert.notEqual(
    workspaceScrollKey(location),
    workspaceScrollKey({ ...location, projectId: "other" }),
  );
  assert.notEqual(
    workspaceScrollKey(location),
    workspaceScrollKey({ ...location, mode: "chat", conversationId: "chat" }),
  );
});

/** 编译实际导航钩子，替换网络、草稿屏障及最小状态容器 */
async function application() {
  const fixtures = {
    react: `let values = [], index = 0, effects = [], cleanups = [];
      export function begin() { index = 0; }
      export function useState(initial) {
        const key = index++;
        if (!(key in values)) values[key] = initial;
        return [values[key], value => values[key] = typeof value === "function" ? value(values[key]) : value];
      }
      export function useRef(value) { return values[index++] ??= {current:value}; }
      export function useEffect(effect, deps) {
        const key = index++, previous = values[key];
        if (!previous || deps.some((value, i) => value !== previous[i])) {
          values[key] = deps;
          effects.push(() => { cleanups[key]?.(); cleanups[key] = effect(); });
        }
      }
      export function flushEffects() { for (const effect of effects.splice(0)) effect(); }
      export function dispose() { for (const cleanup of cleanups) cleanup?.(); }`,
    services: `export const saved = new Map(), control = {calls:0, failure:"", delayed:false, waiting:[],namespace:"synthetic"};
      export const storage = {namespace:()=>control.namespace,setItem:(key,value)=>saved.set(key,value)};
      export const loadLocal = (key,fallback) => saved.has(key) ? JSON.parse(saved.get(key)) : fallback;
      export async function api() { return {project_id:"wrong-project"}; }
      export async function flushDrafts() {
        control.calls++;
        if (control.failure) throw new Error(control.failure);
        if (control.delayed) await new Promise(done => control.waiting.push(done));
      }`,
  };
  const result = await build({
    stdin: {
      contents: `export {useWorkspaceNavigation} from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/useWorkspaceNavigation";
        export * from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/workspaceSession";
        export * from "react"; export * from "fixture/services";`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    format: "esm",
    write: false,
    plugins: [
      {
        name: "navigation-fixtures",
        setup(builder) {
          builder.onResolve({ filter: /^react$/ }, () => ({
            path: "react",
            namespace: "fixture",
          }));
          builder.onResolve(
            {
              filter:
                /^(fixture\/services|@resume-maker\/plugin-sdk\/shared\/lib\/)/,
            },
            () => ({ path: "services", namespace: "fixture" }),
          );
          builder.onLoad(
            { filter: /.*/, namespace: "fixture" },
            ({ path }) => ({ contents: fixtures[path] }),
          );
        },
      },
    ],
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}#${crypto.randomUUID()}`
  );
}

/** 模拟浏览器历史栈，保留真实前进后退及拒绝后的回退行为 */
function browser(href) {
  const listeners = new Set(),
    entries = [{ url: href, state: null }];
  let position = 0;
  const window = {
    location: { href },
    addEventListener: (name, listener) => listeners.add(listener),
    removeEventListener: (name, listener) => listeners.delete(listener),
  };
  const history = {
    state: null,
    replaceState(value, title, url) {
      entries[position] = {
        state: value,
        url: new URL(url, window.location.href).href,
      };
      apply();
    },
    pushState(value, title, url) {
      entries.splice(++position, entries.length, {
        state: value,
        url: new URL(url, window.location.href).href,
      });
      apply();
    },
    go(offset) {
      position = Math.max(0, Math.min(entries.length - 1, position + offset));
      apply();
      for (const listener of listeners) listener({ state: history.state });
    },
  };
  /** 浏览器先更新地址，再通知应用处理当前位置 */
  function apply() {
    window.location.href = entries[position].url;
    history.state = entries[position].state;
  }
  return { window, history, entries };
}

/** 安装独立浏览器及导航状态，测试结束时清理事件监听 */
async function harness(
  t,
  href = "http://local/?workspace=personal&project=p",
  historyIndex = 0,
) {
  const module = await application();
  const instance = browser(href);
  instance.history.replaceState(
    { resumeWorkspace: { index: historyIndex } },
    "",
    href,
  );
  const previous = {
    window: globalThis.window,
    history: globalThis.history,
    sessionStorage: globalThis.sessionStorage,
  };
  const session = new Map();
  Object.assign(globalThis, {
    window: instance.window,
    history: instance.history,
    sessionStorage: {
      getItem: (key) => session.get(key) ?? null,
      setItem: (key, value) => session.set(key, value),
    },
  });
  t.after(() => {
    module.dispose();
    Object.assign(globalThis, previous);
  });
  const notices = [];
  const options = {
    loaded: true,
    location: DEFAULT_LOCATION,
    state: state(),
    areas: ["projects", "personal", "structure"],
    pages: [],
    chatAvailable: true,
    defaultProjectId: "p",
    blocked: () => false,
    onRestore: (location) => (options.location = location),
    notify: (notice) => notices.push(notice),
  };
  /** 执行一次真实钩子的状态、监听收尾 */
  let navigation;
  /** 执行一次真实钩子的状态、监听收尾 */
  function render() {
    module.begin();
    navigation = module.useWorkspaceNavigation(options);
    module.flushEffects();
  }
  render();
  await settle();
  render();
  return {
    module,
    instance,
    options,
    notices,
    render,
    cancelPending: () => navigation.cancelPending(),
  };
}

/** 处理微任务、草稿屏障及导航回调 */
async function settle() {
  await new Promise((done) => setImmediate(done));
}

test("刷新恢复地址中的工作区，前进后退等待草稿且不创建重复历史", async (t) => {
  const { module, instance, options, render } = await harness(t, undefined, 7);
  assert.equal(options.location.area, "personal");
  assert.equal(instance.history.state.resumeWorkspace.index, 7);
  options.location = { ...options.location, area: "structure" };
  render();
  assert.equal(instance.entries.length, 2);
  assert.equal(instance.history.state.resumeWorkspace.index, 8);
  instance.history.go(-1);
  await settle();
  render();
  assert.equal(options.location.area, "personal");
  instance.history.go(1);
  await settle();
  render();
  assert.equal(options.location.area, "structure");
  assert.equal(module.control.calls, 2);
  assert.equal(instance.entries.length, 2);
});

test("刷新地址引用其他项目的历史版本时恢复当前项目最新版本", async (t) => {
  const { options } = await harness(
    t,
    "http://local/?workspace=projects&project=p&revision=foreign",
  );
  assert.equal(options.location.projectId, "p");
  assert.equal(options.location.revisionId, "r1");
});

test("位置缓存按资料目录、本页隔离，不争用业务草稿，存储不可用仍可导航", async (t) => {
  const { module, options, render } = await harness(t);
  module.saveWorkspaceSession("scroll.test", { top: 200 });
  assert.deepEqual(module.readWorkspaceSession("scroll.test", {}), {
    top: 200,
  });
  module.control.namespace = "other-data";
  assert.deepEqual(module.readWorkspaceSession("scroll.test", {}), {});
  assert.equal(module.saved.size, 0);
  globalThis.sessionStorage = {
    getItem() {
      throw new Error("不可用");
    },
    setItem() {
      throw new Error("不可用");
    },
  };
  options.location = { ...options.location, area: "structure" };
  assert.doesNotThrow(render);
  assert.deepEqual(module.readWorkspaceSession("scroll.test", {}), {});
});

test("草稿保存失败或发布期间拒绝后退，保留原工作区及历史位置", async (t) => {
  const { module, instance, options, notices, render } = await harness(t);
  options.location = { ...options.location, area: "structure" };
  render();
  module.control.failure = "草稿冲突";
  instance.history.go(-1);
  await settle();
  render();
  assert.equal(options.location.area, "structure");
  assert.match(instance.window.location.href, /workspace=structure/);
  assert.equal(notices.at(-1).text, "草稿冲突");
  module.control.failure = "";
  options.blocked = () => true;
  instance.history.go(-1);
  await settle();
  assert.equal(module.control.calls, 1);
  assert.equal(options.location.area, "structure");
  assert.equal(instance.entries.length, 2);
});

test("连续后退只采用最后一次目标，迟到草稿响应不能抢回位置", async (t) => {
  const { module, instance, options, render } = await harness(t);
  for (const area of ["structure", "projects"]) {
    options.location = { ...options.location, area };
    render();
  }
  module.control.delayed = true;
  instance.history.go(-1);
  await settle();
  instance.history.go(-1);
  await settle();
  assert.equal(module.control.waiting.length, 2);
  module.control.waiting[1]();
  await settle();
  render();
  module.control.waiting[0]();
  await settle();
  render();
  assert.equal(options.location.area, "personal");
  assert.match(instance.window.location.href, /workspace=personal/);
});

test("后退等待草稿时新点击取消旧导航，保留原历史且迟到结果不能覆盖新位置", async (t) => {
  const { module, instance, options, render, cancelPending } = await harness(t);
  options.location = { ...options.location, area: "structure" };
  render();
  module.control.delayed = true;
  instance.history.go(-1);
  await settle();
  await cancelPending();
  assert.match(instance.window.location.href, /workspace=structure/);
  options.location = { ...options.location, area: "projects" };
  render();
  module.control.waiting[0]();
  await settle();
  render();
  assert.equal(options.location.area, "projects");
  assert.match(instance.window.location.href, /workspace=projects/);
  assert.equal(instance.entries.length, 3);
  assert.equal(instance.history.state.resumeWorkspace.index, 2);
  module.control.delayed = false;
  instance.history.go(-1);
  await settle();
  render();
  assert.equal(options.location.area, "structure");
});

test("无需等待的工作区切换也会取消迟到的后退恢复", async (t) => {
  const { module, instance, options, render } = await harness(t);
  options.location = { ...options.location, area: "structure" };
  render();
  module.control.delayed = true;
  instance.history.go(-1);
  await settle();
  options.location = { ...options.location, area: "projects" };
  render();
  await settle();
  render();
  module.control.waiting[0]();
  await settle();
  render();
  assert.equal(options.location.area, "projects");
  assert.match(instance.window.location.href, /workspace=projects/);
  assert.equal(instance.entries.length, 3);
});
