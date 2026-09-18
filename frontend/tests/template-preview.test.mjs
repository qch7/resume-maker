import { test } from "node:test";
import assert from "node:assert/strict";
import { createPreviewQueue } from "../src/features/resumes/templatePreviewQueue.ts";
import { templatePreviewInput } from "../src/features/resumes/templatePreviewInput.ts";

/** 由测试控制异步渲染完成时机；模拟 Word 比输入更慢的情况 */
function harness(t) {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const calls = [];
  const events = [];
  const queue = createPreviewQueue(
    /* 保存请求的完成入口且不启动真实 Word */ (key, signal) =>
      new Promise(
        /* 将任务加入模拟请求列表 */ (resolve, reject) =>
          calls.push({ key, signal, resolve, reject }),
      ),
    /* 记录用户能观察到的状态 */ (state) => events.push(state),
    1000,
  );
  t.after(/* 测试完成时回收队列 */ () => queue.dispose());
  return { queue, calls, events };
}

test("continuous typing is debounced and identical inputs are reused", /* 连续输入停顿后只启动一次排版 */ async (t) => {
  const { queue, calls, events } = harness(t);
  queue.submit("first");
  t.mock.timers.tick(800);
  queue.submit("second");
  t.mock.timers.tick(800);
  assert.equal(calls.length, 0);
  t.mock.timers.tick(200);
  assert.deepEqual(
    calls.map(/* 读取实际排版输入 */ (call) => call.key),
    ["second"],
  );
  calls[0].resolve("page");
  await Promise.resolve();
  queue.submit("second");
  t.mock.timers.tick(2000);
  assert.equal(calls.length, 1);
  assert.equal(events.at(-1).status, "ready");
});

test("an in-flight render is followed only by the latest input", /* Word 请求不能因按键取消；过时返回值不能覆盖新模板 */ async (t) => {
  const { queue, calls, events } = harness(t);
  queue.submit("template-a");
  t.mock.timers.tick(1000);
  queue.submit("intermediate");
  t.mock.timers.tick(1000);
  queue.submit("template-b");
  t.mock.timers.tick(1000);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].signal.aborted, false);
  calls[0].resolve("old page");
  await Promise.resolve();
  assert.deepEqual(
    calls.map(/* 检查已启动的请求序列 */ (call) => call.key),
    ["template-a", "template-b"],
  );
  assert.equal(
    events.some(/* 旧页不得发布为最新结果 */ (event) => event.result),
    false,
  );
  calls[1].resolve("new page");
  await Promise.resolve();
  assert.equal(events.at(-1).result.value, "new page");
});

test("errors can be retried and missing input invalidates late results", /* 同输入允许失败重试；切回内置模板后不接收旧图片 */ async (t) => {
  const { queue, calls, events } = harness(t);
  queue.submit("input");
  t.mock.timers.tick(1000);
  calls[0].reject(new Error("Word unavailable"));
  await Promise.resolve();
  assert.equal(events.at(-1).error, "Word unavailable");
  queue.submit("input", true);
  t.mock.timers.tick(1000);
  assert.equal(calls.length, 2);
  queue.submit(null);
  calls[1].resolve("late page");
  await Promise.resolve();
  assert.deepEqual(events.at(-1), {
    key: null,
    status: "idle",
    result: undefined,
  });
});

test("unmount suppresses late responses and queued work", /* 卸载组件后既不修改状态；也不启动待处理的 Word 请求 */ async (t) => {
  const { queue, calls, events } = harness(t);
  queue.submit("first");
  t.mock.timers.tick(1000);
  queue.submit("second");
  t.mock.timers.tick(1000);
  queue.dispose();
  const length = events.length;
  calls[0].resolve("late");
  await Promise.resolve();
  assert.equal(calls[0].signal.aborted, true);
  assert.equal(calls.length, 1);
  assert.equal(events.length, length);
});

test("payload follows unsaved content, visibility and order without saving references", /* 工作副本进入预览；改名不触发排版；正式引用和删掉的勾选仍保持原样 */ () => {
  const revision = {
    id: "revision",
    project_id: "project",
    content: {
      title: "Pinned",
      highlights: [{ id: "a" }, { id: "b" }, { id: "c" }],
    },
  };
  const draft = {
    id: "resume",
    name: "Name",
    version: 1,
    template_id: "template",
    document: {
      personal: { name: "Unsaved", hidden_fields: ["email"] },
      sections: [],
    },
    items: [
      {
        project_id: "project",
        revision_id: "revision",
        highlight_ids: ["a", "b", "c"],
      },
    ],
  };
  const sources = {
    project: {
      ...revision,
      content: { title: "Typing", highlights: [{ id: "c" }, { id: "a" }] },
    },
  };
  const original = structuredClone(draft);
  const revisions = { revision };
  const key = templatePreviewInput(draft, revisions, sources);
  assert.equal(JSON.parse(key).items[0].content.title, "Typing");
  assert.deepEqual(JSON.parse(key).items[0].highlight_ids, ["c", "a"]);
  assert.deepEqual(JSON.parse(key).document, draft.document);
  assert.deepEqual(draft, original);
  assert.equal(
    templatePreviewInput(
      { ...draft, name: "Renamed", version: 2 },
      revisions,
      sources,
    ),
    key,
  );
  assert.notEqual(
    templatePreviewInput(
      { ...draft, template_id: "other" },
      revisions,
      sources,
    ),
    key,
  );
  assert.equal(templatePreviewInput(draft, {}, sources), null);
  const builtin = JSON.parse(
    templatePreviewInput({ ...draft, template_id: null }, revisions, sources),
  );
  assert.equal(builtin.template_id, null);
  assert.deepEqual(builtin.document, draft.document);
  assert.equal(builtin.items[0].content.title, "Typing");
  assert.equal(
    templatePreviewInput({ ...draft, document: null }, revisions, sources),
    null,
  );
});
