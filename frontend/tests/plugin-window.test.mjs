import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

/** 编译实际窗口协调模块，只有浏览器网络和页面元素由测试提供 */
async function windowModule() {
  const output = buildSync({
    stdin: {
      contents: `export * from "./src/plugins/window";
        export { clientExtensions } from "./src/plugins/extensions";
        export { registerDraft } from "./src/shared/lib/draftRegistry";
        export { setCapabilities, capabilities } from "./src/shared/lib/capabilities";
        export { storage } from "./src/shared/lib/storage";
        export { api } from "./src/shared/lib/api";`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    platform: "browser",
    format: "esm",
    write: false,
  }).outputFiles[0].text;
  const module = await import(
    `data:text/javascript;base64,${Buffer.from(output).toString("base64")}#${crypto.randomUUID()}`
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

/** 运行当前实例的真实注册命令，以完成信号控制收尾 */
function command(module, owner, onFinish) {
  let finish, signal;
  const id = `${owner}/work`;
  const dispose = module.clientExtensions.contribute(
    {
      id: owner,
      entry: { mode: "trusted-client", entry: "client/index.js" },
      contributes: { commands: [id] },
    },
    "commands",
    id,
    {
      title: owner,
      run(context) {
        signal = context.signal;
        return new Promise((resolve) => {
          finish = () => {
            onFinish();
            resolve();
          };
        });
      },
    },
  );
  return {
    id,
    dispose,
    pending: module.clientExtensions.execute(id),
    signal: () => signal,
    finish: () => finish(),
  };
}

test("整页切换前等待所有实例命令结束并保存最终草稿", async (t) => {
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url === "/api/plugins/windows")
      return Response.json({ pending_plan: "change", acknowledged: false });
    if (url === "/api/plugins/plans/change")
      return Response.json({ affected: ["community.one"], generation: 7 });
    assert.equal(url, "/api/plugins/plans/change/acknowledge");
    events.push("ack");
    return Response.json({});
  });
  const previous = globalThis.document;
  globalThis.document = { querySelector: () => ({ content: "synthetic" }) };
  const events = [];
  const module = await windowModule();
  let text = "initial";
  const remove = module.registerDraft("synthetic", async () => {
    events.push(text);
  });
  const affected = command(module, "community.one", () => {
    text = "final";
    events.push("finished");
  });
  const other = command(module, "community.two", () => {
    text = "other-final";
    events.push("other-finished");
  });
  try {
    await Promise.resolve();
    const connecting = module.connectWindow();
    await new Promise((resolve) => setTimeout(resolve, 25));
    assert.equal(affected.signal().aborted, true);
    assert.equal(other.signal().aborted, true);
    assert.ok(!events.includes("ack"));
    affected.finish();
    await affected.pending;
    await Promise.resolve();
    assert.ok(!events.includes("ack"));
    other.finish();
    await other.pending;
    await connecting;
    assert.deepEqual(events, [
      "initial",
      "finished",
      "other-finished",
      "other-final",
      "ack",
    ]);
    await assert.rejects(
      module.clientExtensions.execute(affected.id),
      /切换|排空/,
    );
    await assert.rejects(
      module.clientExtensions.execute(other.id),
      /切换|排空/,
    );
  } finally {
    affected.finish();
    other.finish();
    await Promise.all([affected.pending, other.pending]);
    await affected.dispose();
    await other.dispose();
    remove();
    globalThis.document = previous;
  }
});

test("命令忽略取消时窗口超时且不确认，真实结束后重试并在计划取消后解除冻结", async (t) => {
  let acknowledged = 0,
    pendingPlan = "change";
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url === "/api/plugins/windows")
      return Response.json({ pending_plan: pendingPlan, acknowledged: false });
    if (url === "/api/plugins/plans/change")
      return Response.json({ affected: ["community.one"], generation: 7 });
    assert.equal(url, "/api/plugins/plans/change/acknowledge");
    acknowledged++;
    return Response.json({});
  });
  const previous = globalThis.document;
  globalThis.document = { querySelector: () => ({ content: "synthetic" }) };
  const module = await windowModule();
  const active = command(module, "community.unaffected", () => {});
  try {
    await Promise.resolve();
    await module.connectWindow();
    assert.equal(active.signal().aborted, true);
    assert.equal(acknowledged, 0);
    assert.match(module.windowNotice(), /未结束/);
    active.finish();
    await active.pending;
    await module.connectWindow();
    assert.equal(acknowledged, 1);
    await assert.rejects(
      module.clientExtensions.execute(active.id),
      /切换|排空/,
    );
    pendingPlan = null;
    await module.connectWindow();
    assert.equal(module.windowNotice(), "");
    const resumed = module.clientExtensions.execute(active.id);
    await Promise.resolve();
    active.finish();
    await resumed;
  } finally {
    active.finish();
    await active.pending;
    await active.dispose();
    globalThis.document = previous;
  }
});

test("实际刷新入口等待全部命令收尾，期间新注册实例也不能启动命令", async () => {
  const previousDocument = globalThis.document;
  const previousLocation = globalThis.location;
  globalThis.document = { querySelector: () => ({ content: "synthetic" }) };
  const events = [];
  globalThis.location = { reload: () => events.push("reload") };
  const module = await windowModule();
  const active = command(module, "community.unaffected", () =>
    events.push("finished"),
  );
  let dispose;
  try {
    await Promise.resolve();
    const reloading = module.reloadWindow();
    assert.equal(active.signal().aborted, true);
    assert.deepEqual(events, []);
    dispose = module.clientExtensions.contribute(
      {
        id: "community.late",
        entry: { mode: "trusted-client", entry: "index.js" },
        contributes: { commands: ["community.late/start"] },
      },
      "commands",
      "community.late/start",
      { title: "late", run() {} },
    );
    await assert.rejects(
      module.clientExtensions.execute("community.late/start"),
      /切换|排空/,
    );
    active.finish();
    await active.pending;
    await reloading;
    assert.deepEqual(events, ["finished", "reload"]);
  } finally {
    active.finish();
    await active.pending;
    await active.dispose();
    await dispose?.();
    globalThis.document = previousDocument;
    globalThis.location = previousLocation;
  }
});

test("准备期间注册冲突不会永久停止心跳，计划取消后可以重新加入", async (t) => {
  const previous = globalThis.document;
  globalThis.document = { querySelector: () => ({ content: "synthetic" }) };
  let attempts = 0;
  t.mock.method(globalThis, "fetch", async () => {
    attempts++;
    return attempts === 1
      ? Response.json({ detail: "正在切换" }, { status: 409 })
      : Response.json({ pending_plan: null, acknowledged: false });
  });
  try {
    const module = await windowModule();
    await module.connectWindow();
    assert.match(module.windowNotice(), /切换/);
    await module.connectWindow();
    assert.equal(attempts, 2);
    assert.equal(module.windowNotice(), "");
  } finally {
    globalThis.document = previous;
  }
});

test("并发刷新共用一次保存，保存失败后保留页面并允许重试", async (t) => {
  const previousDocument = globalThis.document,
    previousLocation = globalThis.location;
  globalThis.document = { querySelector: () => ({ content: "synthetic" }) };
  let reloads = 0,
    saves = 0;
  globalThis.location = {
    reload: () => {
      reloads++;
    },
  };
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({ pending_plan: null, acknowledged: false }),
  );
  try {
    const module = await windowModule();
    const first = module.reloadWindow(async () => {
      saves++;
      throw new Error("synthetic save conflict");
    });
    const second = module.reloadWindow(async () => {
      saves++;
    });
    assert.equal(first, second);
    await assert.rejects(first, /save conflict/);
    assert.equal(reloads, 0);
    await module.connectWindow();
    assert.equal(module.windowNotice(), "");
    await module.reloadWindow(async () => {
      saves++;
    });
    assert.equal(saves, 2);
    assert.equal(reloads, 1);
  } finally {
    globalThis.document = previousDocument;
    globalThis.location = previousLocation;
  }
});

/** 使用实际存储及请求模块，模拟旧窗口返回时服务器已经提交了新代次 */
async function recoveryWindow(t) {
  const previous = ["document", "location", "localStorage"].map((key) => [
    key,
    Object.getOwnPropertyDescriptor(globalThis, key),
  ]);
  const local = {};
  const state = { generation: 8, writable: true, reloads: 0, writes: [] };
  Object.defineProperties(local, {
    getItem: { value: (key) => local[key] ?? null },
    setItem: {
      value: (key, value) => {
        if (!state.writable) throw new Error("synthetic quota exceeded");
        local[key] = value;
      },
    },
    removeItem: { value: (key) => delete local[key] },
  });
  for (const [key, value] of Object.entries({
    document: { querySelector: () => ({ content: "synthetic" }) },
    location: { reload: () => state.reloads++ },
    localStorage: local,
  }))
    Object.defineProperty(globalThis, key, { configurable: true, value });
  const modules = [];
  t.after(() => {
    for (const module of modules) module.storage.dispose();
    for (const [key, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url === "/api/capabilities")
      return Response.json({ generation: state.generation, ready: true });
    if (url === "/api/workspace-storage")
      return Response.json({ namespace: "synthetic", values: {} });
    if (url === "/api/plugins/windows")
      return Response.json({ detail: "插件配置已变化" }, { status: 409 });
    state.writes.push({
      url,
      generation: options.headers["x-resume-generation"],
    });
    return Response.json({ detail: "草稿写入被拒绝" }, { status: 409 });
  });
  const module = await windowModule();
  modules.push(module);
  await module.storage.initialize();
  return { module, modules, state, local };
}

test("旧代次刷新等命令及全部草稿收尾，输入只作为新窗口的恢复副本", async (t) => {
  const { module, modules, state, local } = await recoveryWindow(t);
  module.storage.setItem("rm.resume.v2.new", "离线输入");
  const active = command(module, "community.offline", () => {
    module.storage.setItem("rm.resume.v2.new", "命令结束后的输入");
  });
  const removeDraft = module.registerDraft("rejected-domain", () =>
    module.api("/projects/synthetic/draft", "PUT", { value: "合成草稿" }),
  );
  let finishDraft;
  const removeLate = module.registerDraft(
    "late-domain",
    () =>
      new Promise((resolve) => {
        finishDraft = () => {
          module.storage.setItem("rm.chat.synthetic", "最后一份输入");
          resolve();
        };
      }),
  );
  try {
    await module.connectWindow();
    assert.match(module.windowNotice(), /配置已变化/);
    const reloading = module.reloadWindow();
    let settled = false;
    void reloading.then(
      () => (settled = true),
      () => (settled = true),
    );
    assert.equal(active.signal().aborted, true);
    assert.equal(state.reloads, 0);
    active.finish();
    await active.pending;
    await new Promise(setImmediate);
    assert.equal(settled, false);
    assert.equal(state.reloads, 0);
    finishDraft();
    await reloading;
    assert.equal(state.reloads, 1);
    assert.equal(module.capabilities().generation, 7);
    assert.ok(state.writes.length > 0);
    assert.ok(state.writes.every((request) => request.generation === "7"));
    assert.deepEqual(
      Object.values(local).map((value) => JSON.parse(value).plugin_generation),
      [7, 7],
    );
    module.storage.dispose();
    const restored = await windowModule();
    modules.push(restored);
    restored.setCapabilities({ ...restored.capabilities(), generation: 8 });
    await restored.storage.initialize();
    assert.equal(restored.storage.getItem("rm.resume.v2.new"), null);
    assert.deepEqual(
      restored.storage.recoveries().map(({ key, value }) => ({ key, value })),
      [
        { key: "rm.resume.v2.new", value: "命令结束后的输入" },
        { key: "rm.chat.synthetic", value: "最后一份输入" },
      ],
    );
    const writes = state.writes.length;
    await restored.storage.flush();
    assert.equal(state.writes.length, writes);
  } finally {
    finishDraft?.();
    active.finish();
    await active.pending;
    await active.dispose();
    removeLate();
    removeDraft();
  }
});

test("旧代次输入无法写入恢复副本时阻止刷新，存储恢复后可重试", async (t) => {
  const { module, state, local } = await recoveryWindow(t);
  state.writable = false;
  module.storage.setItem("rm.resume.v2.new", "不能丢失的输入");
  await assert.rejects(module.reloadWindow(), /恢复副本不可用/);
  assert.equal(state.reloads, 0);
  assert.deepEqual(Object.keys(local), []);
  state.writable = true;
  await module.reloadWindow();
  assert.equal(state.reloads, 1);
  assert.equal(JSON.parse(Object.values(local)[0]).value, "不能丢失的输入");
});

test("同代次普通草稿冲突不因存在浏览器副本而绕过处理", async (t) => {
  const { module, state, local } = await recoveryWindow(t);
  state.generation = 7;
  module.storage.setItem("rm.resume.v2.new", "有冲突的输入");
  await assert.rejects(module.reloadWindow(), /草稿未写入/);
  assert.equal(state.reloads, 0);
  assert.equal(Object.keys(local).length, 1);
  assert.equal(module.storage.warnBeforeUnload(), true);
});

test("心跳报告页面名称及保存失败，浏览器标签显示服务分配的窗口序号", async (t) => {
  const previous = globalThis.document;
  globalThis.document = {
    title: "",
    querySelector: () => ({ content: "synthetic" }),
  };
  const bodies = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url === "/api/plugins/windows") {
      bodies.push(JSON.parse(options.body));
      return Response.json({
        pending_plan: "change",
        acknowledged: false,
        number: 3,
      });
    }
    assert.equal(url, "/api/plugins/plans/change");
    return Response.json({ affected: [], generation: 7 });
  });
  try {
    const module = await windowModule();
    const removeTitle = module.registerWindowTitle("ResumeMaker · 合成项目");
    const removePage = module.registerWindowTitle("ResumeMaker · 扩展页面", 1);
    const removeDraft = module.registerDraft("conflict", async () => {
      throw new Error("合成草稿版本冲突");
    });
    try {
      await module.connectWindow();
      assert.equal(bodies[0].title, "ResumeMaker · 扩展页面");
      assert.equal(
        globalThis.document.title,
        "ResumeMaker · 扩展页面［窗口 3］",
      );
      removePage();
      await module.connectWindow();
      assert.equal(bodies[1].title, "ResumeMaker · 合成项目");
      assert.equal(bodies[1].status, "合成草稿版本冲突");
      assert.equal(
        globalThis.document.title,
        "ResumeMaker · 合成项目［窗口 3］",
      );
      assert.equal(module.windowNotice(), "合成草稿版本冲突");
    } finally {
      removeDraft();
      removePage();
      removeTitle();
    }
  } finally {
    globalThis.document = previous;
  }
});

test("定位只标记目标标签并尝试聚焦，不改变保存状态或发送确认", async (t) => {
  const previousDocument = globalThis.document,
    previousWindow = globalThis.window,
    previousChannel = globalThis.BroadcastChannel;
  const channels = [];
  class Channel {
    constructor() {
      channels.push(this);
    }
    postMessage(value) {
      this.sent = value;
    }
    close() {
      this.closed = true;
    }
  }
  let focused = 0;
  const events = new Map();
  globalThis.document = {
    title: "",
    querySelector: () => ({ content: "synthetic" }),
  };
  globalThis.window = {
    focus: () => focused++,
    addEventListener: (name, callback) => events.set(name, callback),
    removeEventListener: (name) => events.delete(name),
  };
  globalThis.BroadcastChannel = Channel;
  t.mock.method(globalThis, "fetch", async (url) => {
    assert.ok(
      ["/api/plugins/windows", "/api/plugins/windows/close"].includes(url),
    );
    return Response.json({
      pending_plan: null,
      acknowledged: false,
      number: 2,
    });
  });
  try {
    const module = await windowModule();
    const removeTitle = module.registerWindowTitle("ResumeMaker · 目标项目");
    const dispose = module.startWindow();
    try {
      await new Promise(setImmediate);
      assert.equal(module.locateWindow("another"), true);
      assert.deepEqual(channels[0].sent, { type: "locate", id: "another" });
      assert.equal(focused, 0);
      channels[0].onmessage({ data: { type: "locate", id: "another" } });
      assert.equal(focused, 0);
      channels[0].onmessage({ data: { type: "locate", id: module.windowId } });
      assert.equal(focused, 1);
      assert.equal(
        globalThis.document.title,
        "【待保存】ResumeMaker · 目标项目［窗口 2］",
      );
      assert.equal(module.windowNotice(), "");
      events.get("pointerdown")();
      assert.equal(
        globalThis.document.title,
        "ResumeMaker · 目标项目［窗口 2］",
      );
    } finally {
      await dispose();
      removeTitle();
    }
    assert.equal(channels[0].closed, true);
    assert.equal(events.size, 0);
    assert.equal(module.locateWindow("another"), false);
  } finally {
    globalThis.document = previousDocument;
    globalThis.window = previousWindow;
    globalThis.BroadcastChannel = previousChannel;
  }
});
