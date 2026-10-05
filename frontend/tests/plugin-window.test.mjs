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

test("窗口确认等受影响命令结束后再保存最终草稿，其他实例仍可完成工作", async (t) => {
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
  const other = command(module, "community.two", () => {});
  try {
    await Promise.resolve();
    const connecting = module.connectWindow();
    await new Promise((resolve) => setTimeout(resolve, 25));
    assert.equal(affected.signal().aborted, true);
    assert.equal(other.signal().aborted, false);
    assert.ok(!events.includes("ack"));
    affected.finish();
    await affected.pending;
    await connecting;
    assert.deepEqual(events, ["initial", "finished", "final", "ack"]);
    await assert.rejects(
      module.clientExtensions.execute(affected.id),
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
  const active = command(module, "community.one", () => {});
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
