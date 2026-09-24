import assert from "node:assert/strict";
import { test } from "node:test";
import { flushDrafts, registerDraft } from "../src/shared/lib/draftRegistry.ts";

test("navigation flush awaits drafts from independent features", /* 验证导航等待所有业务草稿完成写入 */ async () => {
  // 用受控 Promise 验证会话和经历草稿全部完成前不能继续导航
  let finishChat;
  const chat = new Promise(
    /* 提供可控的完成信号 */ (resolve) => {
      finishChat = resolve;
    },
  );
  let experienceSaved = false;
  const removeChat = registerDraft(
    "test-chat",
    /* 模拟当前业务的草稿写入，由共享注册表等待或传播错误 */ () => chat,
  );
  const removeExperience = registerDraft(
    "test-experience",
    /* 模拟当前业务的草稿写入，由共享注册表等待或传播错误 */ async () => {
      experienceSaved = true;
    },
  );
  try {
    let complete = false;
    const pending = flushDrafts().then(
      /* 记录异步刷新全部完成的时刻，供等待行为断言使用 */ () => {
        complete = true;
      },
    );
    await Promise.resolve();
    assert.equal(experienceSaved, true);
    assert.equal(complete, false);
    finishChat();
    await pending;
    assert.equal(complete, true);
  } finally {
    removeChat();
    removeExperience();
  }
});

test("draft conflicts reject the shared navigation flush", /* 验证冲突会拒绝草稿刷新，阻止离开当前编辑现场 */ async () => {
  // 冲突向上传播以保留当前编辑内容
  const unregister = registerDraft(
    "test-conflict",
    /* 模拟当前业务的草稿写入，由共享注册表等待或传播错误 */ async () => {
      throw new Error("草稿冲突");
    },
  );
  try {
    await assert.rejects(flushDrafts(), /草稿冲突/);
  } finally {
    unregister();
  }
});

test("unmounted drafts are no longer flushed", /* 验证卸载解除登记后不会再次写入原字段 */ async () => {
  // 卸载清理后，共享注册表不能继续写入已经离开的字段
  let writes = 0;
  const unregister = registerDraft(
    "test-unmount",
    /* 模拟当前业务的草稿写入，由共享注册表等待或传播错误 */ async () => {
      writes++;
    },
  );
  unregister();
  await flushDrafts();
  assert.equal(writes, 0);
});

test("backup waits for recovery writes created by business draft saves", async () => {
  const steps = [];
  const removeStorage = registerDraft(
    "test-storage",
    async () => {
      steps.push("storage");
    },
    true,
  );
  const removeBusiness = registerDraft("test-business", async () => {
    await Promise.resolve();
    steps.push("business");
  });
  try {
    await flushDrafts();
    assert.deepEqual(steps, ["business", "storage"]);
  } finally {
    removeStorage();
    removeBusiness();
  }
});
