import test from "node:test";
import assert from "node:assert/strict";
import {
  instanceContribution,
  instanceDescriptor,
  instanceIdentifier,
  isolatedPageSource,
} from "../src/plugins/identity.ts";

test("隔离页面使用定义资源地址，两个实例共用同一份代码", () => {
  const digest = "a".repeat(64);
  const entry = `/plugin-assets/community.example/${digest}/client/index.js`;
  assert.equal(
    isolatedPageSource(entry, "http://localhost:8765"),
    `/plugin-ui/community.example/${digest}`,
  );
  assert.throws(() =>
    isolatedPageSource("https://example.com" + entry, "http://localhost:8765"),
  );
});

test("多个客户端实例拥有独立命令和工作流引用", () => {
  const definition = {
    plugin: "example.plugin",
    entry: { mode: "trusted-client", entry: "/synthetic" },
    contributes: { commands: ["example.plugin/save"] },
  };
  const first = instanceDescriptor({ ...definition, id: "example.first" });
  const second = instanceDescriptor({ ...definition, id: "example.second" });
  assert.deepEqual(first.contributes.commands, ["example.first/save"]);
  assert.deepEqual(second.contributes.commands, ["example.second/save"]);
  assert.deepEqual(definition.contributes.commands, ["example.plugin/save"]);
  const step = {
    title: "保存",
    state: "example.plugin/state",
    command: "example.plugin/save",
  };
  assert.deepEqual(instanceContribution(first, "workflow.steps", step), {
    ...step,
    state: "example.first/state",
    command: "example.first/save",
  });
  assert.equal(
    instanceIdentifier(first, "example.second/save"),
    "example.second/save",
  );
  assert.equal(
    instanceIdentifier(first, "example.first/save"),
    "example.first/save",
  );
});
