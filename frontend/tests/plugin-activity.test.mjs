import assert from "node:assert/strict";
import { test } from "node:test";
import { createClientExtensions } from "../src/plugins/extensions.ts";

test("日志展示读取冻结副本，失败隔离且卸载后恢复通用记录", async () => {
  const registry = createClientExtensions();
  const owner = {
    id: "community.example",
    contributes: {
      "activity.presenters": [
        "community.example/good",
        "community.example/bad",
        "community.example/large",
      ],
    },
  };
  const sources = ["synthetic"];
  const dispose = registry.contribute(
    owner,
    "activity.presenters",
    "community.example/good",
    {
      sources,
      present(input) {
        assert.ok(Object.isFrozen(input.payload));
        return {
          title: "合成事件",
          lines: [{ label: "值", text: input.payload.value }],
        };
      },
    },
  );
  sources.push("other");
  registry.contribute(owner, "activity.presenters", "community.example/bad", {
    sources: ["synthetic"],
    present(input) {
      input.payload.value = "changed";
      throw new Error("不应回显的正文");
    },
  });
  registry.contribute(owner, "activity.presenters", "community.example/large", {
    sources: ["synthetic"],
    present() {
      return {
        title: "过大输出",
        lines: [{ label: "值", text: "x".repeat(4001) }],
      };
    },
  });
  const event = { source: "synthetic", payload: { value: "<b>纯文本</b>" } };
  const result = registry.activity(event);
  assert.equal(result.length, 3);
  assert.equal(result.filter((item) => item.error).length, 2);
  assert.equal(
    result.find((item) => !item.error).lines[0].text,
    "<b>纯文本</b>",
  );
  assert.equal(event.payload.value, "<b>纯文本</b>");
  assert.doesNotMatch(JSON.stringify(result), /不应回显/);
  assert.deepEqual(registry.activity({ source: "other" }), []);
  await dispose();
  assert.equal(
    registry.activity(event).some((item) => !item.error),
    false,
  );
});

test("日志贡献必须声明来源，未声明或无效贡献拒绝装载", () => {
  const registry = createClientExtensions();
  const owner = {
    id: "community.example",
    contributes: { "activity.presenters": ["community.example/event"] },
  };
  assert.throws(
    () =>
      registry.contribute(
        owner,
        "activity.presenters",
        "community.example/event",
        {
          sources: [],
          present() {
            return null;
          },
        },
      ),
    /必须声明/,
  );
  assert.throws(
    () =>
      registry.contribute(
        owner,
        "activity.presenters",
        "community.example/missing",
        {
          sources: ["synthetic"],
          present() {
            return null;
          },
        },
      ),
    /未声明/,
  );
});
