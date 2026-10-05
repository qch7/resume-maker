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
        export { setCapabilities } from "./src/shared/lib/capabilities";`,
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
