import assert from "node:assert/strict";
import { test } from "node:test";
import { createClientExtensions, jsonCopy } from "../src/plugins/extensions.ts";
import { updateExtension } from "../src/features/profile/extensionState.ts";
import { sameResumeDocument } from "../src/features/profile/comparison.ts";
import { newDocument } from "../src/features/profile/document.ts";

/** 构造可发布扩展的清单片段 */
function descriptor(contributes, id = "community.example") {
  return {
    id,
    entry: { mode: "trusted-client", entry: "client/index.js" },
    contributes,
  };
}

test("未声明、冒用命名空间、版本不符及快捷键冲突均阻止激活", async () => {
  const registry = createClientExtensions();
  const id = "community.example/action";
  const owner = descriptor({ commands: [id] });
  const command = { title: "合成操作", shortcut: "Mod+Shift+K", run() {} };
  assert.throws(() =>
    registry.contribute(owner, "commands", "other/action", command),
  );
  assert.throws(() =>
    registry.contribute(owner, "commands", id, command, 0, "2.0.0"),
  );
  const dispose = registry.contribute(owner, "commands", id, command);
  const other = descriptor(
    { commands: ["community.other/action"] },
    "community.other",
  );
  assert.throws(
    () =>
      registry.contribute(other, "commands", "community.other/action", {
        ...command,
        shortcut: "Shift+Mod+k",
      }),
    /快捷键冲突/,
  );
  await dispose();
  await assert.rejects(registry.execute(id), /不可用/);
});

test("命令卸载发送取消并等待实际结束，重复触发不并行执行", async () => {
  const registry = createClientExtensions();
  const id = "community.example/action";
  let cancelled = false;
  const dispose = registry.contribute(
    descriptor({ commands: [id] }),
    "commands",
    id,
    {
      title: "等待取消",
      run({ signal }) {
        return new Promise((resolve) =>
          signal.addEventListener(
            "abort",
            () => {
              cancelled = true;
              resolve();
            },
            { once: true },
          ),
        );
      },
    },
  );
  const pending = registry.execute(id);
  await Promise.resolve();
  await assert.rejects(registry.execute(id), /仍在执行/);
  await dispose();
  await pending;
  assert.equal(cancelled, true);
  assert.equal(registry.list("commands").length, 0);
});

test("忽略取消的命令使清理明确失败，实际结束后可重试清理", async () => {
  const registry = createClientExtensions(10);
  const id = "community.example/stuck";
  let finish;
  const dispose = registry.contribute(
    descriptor({ commands: [id] }),
    "commands",
    id,
    {
      title: "合成阻塞",
      run() {
        return new Promise((resolve) => {
          finish = resolve;
        });
      },
    },
  );
  const pending = registry.execute(id);
  await Promise.resolve();
  await assert.rejects(dispose(), /暂不能卸载/);
  finish();
  await pending;
  await dispose();
});

test("步骤读取冻结快照，单个状态错误不影响其他贡献和工作区输入", async () => {
  const registry = createClientExtensions();
  const owner = descriptor({
    commands: ["community.example/open"],
    "workflow.steps": ["community.example/check", "community.example/bad"],
    "workflow.state_contributors": [
      "community.example/state",
      "community.example/bad-state",
    ],
  });
  const cleanup = registry.contribute(
    owner,
    "commands",
    "community.example/open",
    { title: "查看", run() {} },
  );
  registry.contribute(
    owner,
    "workflow.state_contributors",
    "community.example/state",
    {
      evaluate(input) {
        return { done: input.draft.name === "Synthetic", text: "已核对" };
      },
    },
  );
  registry.contribute(
    owner,
    "workflow.state_contributors",
    "community.example/bad-state",
    {
      evaluate(input) {
        input.draft.name = "mutated";
        return { done: true, text: "不会采用" };
      },
    },
  );
  for (const [id, state, order] of [
    ["bad", "bad-state", 200],
    ["check", "state", 10],
  ])
    registry.contribute(
      owner,
      "workflow.steps",
      `community.example/${id}`,
      {
        title: id,
        state: `community.example/${state}`,
        command: "community.example/open",
      },
      order,
    );
  const input = { draft: { name: "Synthetic" } };
  const steps = registry.workflow(input);
  assert.equal(steps[0].status.done, true);
  assert.equal(steps[1].status.done, false);
  assert.match(steps[1].status.text, /暂不可用/);
  assert.equal(input.draft.name, "Synthetic");
  await cleanup();
  assert.equal(registry.workflow(input)[0].available, false);
});

test("资料编辑保留未知命名空间并正确影响保存和导出的新旧判断", () => {
  const original = newDocument();
  original.extensions = {
    "missing.plugin": { display: { hidden: true }, values: [2, 1] },
  };
  const payload = { display: { title: "合成字段", text: "42" }, value: 42 };
  const edited = updateExtension(original, "community.example", payload);
  payload.value = 0;
  assert.equal(edited.extensions["community.example"].value, 42);
  assert.deepEqual(
    edited.extensions["missing.plugin"],
    original.extensions["missing.plugin"],
  );
  assert.equal(sameResumeDocument(original, edited), false);
  const reordered = structuredClone(edited);
  reordered.extensions["community.example"] = {
    value: 42,
    display: { text: "42", title: "合成字段" },
  };
  assert.equal(sameResumeDocument(edited, reordered), true);
  reordered.extensions["missing.plugin"].values.reverse();
  assert.equal(sameResumeDocument(edited, reordered), false);
  assert.throws(
    () =>
      updateExtension(original, "community.example", { invalid: undefined }),
    /JSON/,
  );
  assert.throws(() => jsonCopy({ invalid: NaN }), /JSON/);
  assert.throws(
    () =>
      updateExtension(original, "community.example", "a".repeat(1024 * 1024)),
    /1 MB/,
  );
});
