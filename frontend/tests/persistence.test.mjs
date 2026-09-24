import assert from "node:assert/strict";
import { test } from "node:test";
import { createPersistence } from "../src/shared/lib/persistence.ts";

/** 构造可断网及多窗口共用的存储，所有内容均为合成输入 */
function fixture() {
  const local = new Map();
  const values = {};
  let namespace = "test";
  let offline = false;
  let loseResponse = false;
  const instances = [];
  /** 返回同一服务上的独立浏览器窗口 */
  function window(client) {
    const instance = createPersistence({
      client,
      changed: () => {},
      local: {
        keys: () => [...local.keys()],
        getItem: (key) => local.get(key) ?? null,
        setItem: (key, value) => local.set(key, value),
        removeItem: (key) => local.delete(key),
      },
      read: async () => ({ namespace, values: structuredClone(values) }),
      write: async (key, submitted) => {
        if (offline) throw new Error("offline");
        const current = values[key] ?? { value: null, version: 0 };
        if (submitted.value === current.value) return structuredClone(current);
        if (submitted.version !== current.version)
          throw Object.assign(new Error("conflict"), { status: 409 });
        values[key] = { value: submitted.value, version: current.version + 1 };
        if (loseResponse) {
          loseResponse = false;
          throw new Error("lost response");
        }
        return structuredClone(values[key]);
      },
    });
    instances.push(instance);
    return instance;
  }
  return {
    window,
    values,
    local,
    offline: (value) => {
      offline = value;
    },
    loseResponse: () => {
      loseResponse = true;
    },
    namespace: (value) => {
      namespace = value;
    },
    close: () => instances.forEach((instance) => instance.dispose()),
  };
}

test("crash before debounce restores unsent input and later synchronizes", async (t) => {
  const env = fixture();
  t.after(env.close);
  const first = env.window("first");
  await first.initialize();
  first.setItem("rm.resume.v2.new", "unsaved photo and text");
  first.dispose();
  const reopened = env.window("reopened");
  await reopened.initialize();
  assert.equal(reopened.getItem("rm.resume.v2.new"), "unsaved photo and text");
  await reopened.flush();
  assert.equal(env.values["rm.resume.v2.new"].value, "unsaved photo and text");
  assert.equal(env.local.size, 0);
});

test("offline and lost acknowledgement preserve input and retry idempotently", async (t) => {
  const env = fixture();
  t.after(env.close);
  const page = env.window("one");
  await page.initialize();
  page.setItem("rm.honor.draft.new", "recognition corrections");
  env.offline(true);
  await assert.rejects(page.flush());
  assert.equal(page.getItem("rm.honor.draft.new"), "recognition corrections");
  env.offline(false);
  env.loseResponse();
  await assert.rejects(page.flush());
  await page.flush();
  assert.equal(env.values["rm.honor.draft.new"].version, 1);
  assert.equal(page.pending(), false);
});

test("multiple windows protect edits and preserve conflict recovery in database", async (t) => {
  const env = fixture();
  t.after(env.close);
  const left = env.window("left"),
    right = env.window("right");
  await left.initialize();
  await right.initialize();
  left.setItem("rm.template.editor.test", "left plan");
  right.setItem("rm.template.editor.test", "right plan");
  assert.equal(env.local.size, 2);
  await left.flush();
  await assert.rejects(right.flush());
  assert.equal(right.getItem("rm.template.editor.test"), "right plan");
  await right.resolve("rm.template.editor.test", "local");
  assert.equal(env.values["rm.template.editor.test"].value, "right plan");
  assert.ok(
    Object.entries(env.values).some(
      ([key, record]) =>
        key.startsWith("rm.recovery.") && record.value.includes("left plan"),
    ),
  );
});

test("backup restore namespace rejects stale browser outbox", async (t) => {
  const env = fixture();
  t.after(env.close);
  const old = env.window("old");
  await old.initialize();
  old.setItem("rm.resume.v2.new", "post backup change");
  old.dispose();
  env.namespace("restored");
  const restored = env.window("new");
  await restored.initialize();
  assert.equal(restored.getItem("rm.resume.v2.new"), null);
  assert.equal(restored.pending(), false);
  assert.equal(env.local.size, 1);
});

test("loading saved content does not replay adopted journals and retains other conflicts", async (t) => {
  const env = fixture();
  t.after(env.close);
  const closed = env.window("closed");
  await closed.initialize();
  closed.setItem("rm.profile.one", "old local one");
  closed.setItem("rm.profile.two", "old local two");
  closed.dispose();
  env.values["rm.profile.one"] = { value: "saved one", version: 1 };
  env.values["rm.profile.two"] = { value: "saved two", version: 1 };
  const page = env.window("reopened");
  await page.initialize();
  assert.equal(page.issues().length, 2);
  await page.resolve("rm.profile.one", "remote");
  await page.prepareReload();
  assert.equal(page.warnBeforeUnload(), false);
  page.dispose();
  const refreshed = env.window("refreshed");
  await refreshed.initialize();
  assert.equal(refreshed.getItem("rm.profile.one"), "saved one");
  assert.equal(refreshed.getItem("rm.profile.two"), "old local two");
  assert.equal(refreshed.issues().length, 1);
  assert.ok(
    refreshed.recoveries().some((copy) => copy.value === "old local one"),
  );
  assert.equal(refreshed.warnBeforeUnload(), true);
});

test("editing an adopted draft retires its original journal after saving", async (t) => {
  const env = fixture();
  t.after(env.close);
  const closed = env.window("closed");
  await closed.initialize();
  closed.setItem("rm.profile.one", "original local");
  closed.dispose();
  const page = env.window("reopened");
  await page.initialize();
  page.setItem("rm.profile.one", "edited local");
  await page.flush();
  page.dispose();
  const refreshed = env.window("refreshed");
  await refreshed.initialize();
  assert.equal(refreshed.getItem("rm.profile.one"), "edited local");
  assert.equal(refreshed.issues().length, 0);
  assert.ok(
    refreshed.recoveries().some((copy) => copy.value === "original local"),
  );
});

test("changes during a request remain pending until a second confirmed write", async (t) => {
  const local = new Map(),
    values = {};
  let finish;
  let calls = 0;
  const page = createPersistence({
    client: "test",
    changed: () => {},
    local: {
      keys: () => [...local.keys()],
      getItem: (key) => local.get(key),
      setItem: (key, value) => local.set(key, value),
      removeItem: (key) => local.delete(key),
    },
    read: async () => ({ namespace: "test", values }),
    write: async (_key, submitted) => {
      if (++calls === 1)
        await new Promise((resolve) => {
          finish = resolve;
        });
      return { value: submitted.value, version: submitted.version + 1 };
    },
  });
  t.after(() => page.dispose());
  await page.initialize();
  page.setItem("rm.profile.test", "first");
  const saving = page.flush();
  await Promise.resolve();
  await Promise.resolve();
  page.setItem("rm.profile.test", "later");
  finish();
  await assert.rejects(saving);
  assert.equal(page.getItem("rm.profile.test"), "later");
  await page.flush();
  assert.equal(page.pending(), false);
});
