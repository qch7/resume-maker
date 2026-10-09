import { test } from "node:test";
import assert from "node:assert/strict";
import { createStateReader } from "../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/stateReader.ts";
import {
  bindStatePolling,
  createStatePolling,
} from "../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/statePolling.ts";

/** 完成计时器任务的 Promise 收尾 */
async function settle() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
}

test("持续闲置保持原读取频率但只解析一次完整正文", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let requests = 0,
    bodies = 0;
  const read = createStateReader(async (version) => {
    requests++;
    return {
      status: version ? 304 : 200,
      headers: new Headers({ etag: "synthetic" }),
      json: async () => {
        bodies++;
        return { value: 1 };
      },
    };
  });
  const polling = createStatePolling(async (signal) => {
    await read(signal);
  }, assert.fail);
  t.after(() => polling.stop());
  await settle();
  for (let i = 0; i < 10; i++) {
    t.mock.timers.tick(1600);
    await settle();
  }
  assert.equal(requests, 11);
  assert.equal(bodies, 1);
});

test("页面隐藏继续同步，恢复可见和在线及时读取，退出移除监听", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const browser = new EventTarget();
  const page = Object.assign(new EventTarget(), { visibilityState: "visible" });
  let calls = 0;
  const polling = createStatePolling(async () => {
    calls++;
  }, assert.fail);
  const unbind = bindStatePolling(polling, browser, page);
  t.after(() => {
    unbind();
    polling.stop();
  });
  await settle();
  page.visibilityState = "hidden";
  page.dispatchEvent(new Event("visibilitychange"));
  assert.equal(calls, 1);
  t.mock.timers.tick(1600);
  await settle();
  assert.equal(calls, 2);
  page.visibilityState = "visible";
  page.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.equal(calls, 3);
  browser.dispatchEvent(new Event("online"));
  await settle();
  assert.equal(calls, 4);
  unbind();
  polling.stop();
  page.dispatchEvent(new Event("visibilitychange"));
  browser.dispatchEvent(new Event("online"));
  t.mock.timers.tick(60000);
  await settle();
  assert.equal(calls, 4);
});

test("慢读取不重叠，重复恢复事件合并且退出取消真实读取", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0,
    aborts = 0,
    finish;
  const polling = createStatePolling((signal) => {
    calls++;
    signal.addEventListener(
      "abort",
      () => {
        aborts++;
        finish();
      },
      { once: true },
    );
    return new Promise((resolve) => {
      finish = resolve;
    });
  }, assert.fail);
  t.mock.timers.tick(30000);
  polling.wake();
  polling.wake();
  assert.equal(calls, 1);
  polling.stop();
  await settle();
  t.mock.timers.tick(60000);
  assert.equal(calls, 1);
  assert.equal(aborts, 1);
});

test("连续失败有界退避，连接恢复立即读取并恢复正常频率", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0,
    offline = true,
    errors = 0;
  const polling = createStatePolling(
    async () => {
      calls++;
      if (offline) throw new Error("offline");
    },
    () => errors++,
  );
  t.after(() => polling.stop());
  await settle();
  t.mock.timers.tick(3199);
  await settle();
  assert.equal(calls, 1);
  t.mock.timers.tick(1);
  await settle();
  assert.equal(calls, 2);
  offline = false;
  polling.wake();
  await settle();
  assert.equal(calls, 3);
  t.mock.timers.tick(1600);
  await settle();
  assert.equal(calls, 4);
  assert.equal(errors, 2);
});

test("持续失败到达退避上限后仍继续恢复尝试", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  const polling = createStatePolling(
    async () => {
      calls++;
      throw new Error("synthetic offline");
    },
    () => {},
  );
  t.after(() => polling.stop());
  await settle();
  for (const delay of [3200, 6400, 12800, 25600, 30000, 30000]) {
    const before = calls;
    t.mock.timers.tick(delay - 1);
    await settle();
    assert.equal(calls, before);
    t.mock.timers.tick(1);
    await settle();
    assert.equal(calls, before + 1);
  }
  assert.equal(calls, 7);
});

test("迟到或取消的完整响应不能覆盖较新版本缓存", async () => {
  const pending = [];
  const versions = [];
  const read = createStateReader((version) => {
    versions.push(version);
    return new Promise((resolve) => pending.push(resolve));
  });
  const response = (value, etag) => ({
    status: 200,
    headers: new Headers({ etag }),
    json: async () => value,
  });
  const old = read();
  const newer = read();
  pending[1](response("new", "new"));
  assert.equal(await newer, "new");
  pending[0](response("old", "old"));
  await old;
  const current = read();
  pending[2]({ status: 304 });
  assert.equal(await current, "new");
  assert.equal(versions[2], "new");
  const controller = new AbortController();
  const cancelled = read(controller.signal);
  controller.abort();
  pending[3](response("cancelled", "cancelled"));
  await cancelled;
  const after = read();
  pending[4]({ status: 304 });
  assert.equal(await after, "new");
  assert.equal(versions[4], "new");
});

test("重复进入退出不保留旧计时器或跨实例正文", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  for (let i = 0; i < 5; i++) {
    const polling = createStatePolling(async () => {
      calls++;
    }, assert.fail);
    await settle();
    polling.stop();
  }
  t.mock.timers.tick(60000);
  assert.equal(calls, 5);
  const readers = ["left", "right"].map((value) =>
    createStateReader(async () => ({
      status: 200,
      headers: new Headers({ etag: "same" }),
      json: async () => value,
    })),
  );
  assert.deepEqual(await Promise.all(readers.map((read) => read())), [
    "left",
    "right",
  ]);
});
