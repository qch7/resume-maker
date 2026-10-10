import assert from "node:assert/strict";
import { test } from "node:test";
import { createClientExtensions } from "../src/plugins/extensions.ts";

test("预览器按格式选择，状态错误隔离，卸载后撤销", async () => {
  const registry = createClientExtensions();
  const descriptor = {
    id: "community.example",
    contributes: {
      "documents.previewers": [
        "community.example/good",
        "community.example/bad",
      ],
    },
  };
  const formats = ["resume/v1"];
  const dispose = registry.contribute(
    descriptor,
    "documents.previewers",
    "community.example/good",
    {
      title: "合成预览",
      formats,
      component() {
        return null;
      },
      availability(input) {
        assert.ok(Object.isFrozen(input));
        return { available: !!input.input, reason: "需要填写资料" };
      },
    },
  );
  formats.push("undeclared");
  registry.contribute(
    descriptor,
    "documents.previewers",
    "community.example/bad",
    {
      title: "异常预览",
      formats: ["resume/v1"],
      component() {
        return null;
      },
      availability() {
        throw new Error("敏感正文");
      },
    },
  );
  const values = registry.previewers({
    format: "resume/v1",
    input: "immutable",
  });
  assert.equal(values.length, 2);
  assert.equal(values.filter((item) => item.available).length, 1);
  assert.doesNotMatch(JSON.stringify(values), /敏感正文/);
  assert.equal(
    registry.previewers({ format: "undeclared", input: null }).length,
    0,
  );
  assert.equal(
    registry
      .previewers({ format: "resume/v1", input: null })
      .some((item) => item.available),
    false,
  );
  await dispose();
  assert.equal(
    registry
      .previewers({ format: "resume/v1", input: "immutable" })
      .some((item) => item.available),
    false,
  );
});
