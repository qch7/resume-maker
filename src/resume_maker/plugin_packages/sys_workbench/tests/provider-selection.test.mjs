import test from "node:test";
import assert from "node:assert/strict";
import {
  providerChoices,
  replaceProvider,
  replaceProviders,
} from "../client/features/plugins/providerSelection.ts";

const plugins = [
  {
    id: "provider.local",
    required: false,
    provided: { host: { "ocr.backend": { cardinality: "one" } } },
  },
  {
    id: "community.cloud",
    required: false,
    provided: { host: { "ocr.backend": { cardinality: "one" } } },
  },
  { id: "ext.ocr", required: false },
];

test("更换唯一引擎在一份候选里启停，保留消费者并同步显式绑定", () => {
  const selected = ["provider.local", "ext.ocr"];
  const instances = [
    {
      id: "ext.ocr",
      plugin: "ext.ocr",
      bindings: {
        host: { "ocr.backend": "provider.local" },
        remote: { "ocr.backend": "provider.local" },
      },
    },
  ];
  const candidate = replaceProvider(
    plugins,
    selected,
    instances,
    "community.cloud",
  );
  assert.deepEqual(candidate.selected, ["ext.ocr", "community.cloud"]);
  assert.deepEqual(candidate.removed, ["provider.local"]);
  assert.equal(
    candidate.instances[0].bindings.host["ocr.backend"],
    "community.cloud",
  );
  assert.equal(
    candidate.instances[0].bindings.remote["ocr.backend"],
    "community.cloud",
  );
  assert.deepEqual(selected, ["provider.local", "ext.ocr"]);
  assert.equal(instances[0].bindings.host["ocr.backend"], "provider.local");
});

test("同批唯一提供方冲突必须明确选择，不能按包添加顺序抢占", () => {
  const candidates = [...plugins, { ...plugins[1], id: "community.other" }];
  assert.throws(
    () =>
      replaceProviders(
        candidates,
        ["provider.local", "ext.ocr"],
        [],
        ["community.cloud", "community.other"],
      ),
    /唯一能力冲突/,
  );
});

test("必需提供方不能替换，集合提供方保持共存", () => {
  assert.throws(
    () =>
      replaceProvider(
        [{ ...plugins[0], required: true }, plugins[1]],
        ["provider.local"],
        [],
        "community.cloud",
      ),
    /必需/,
  );
  const collection = plugins.slice(0, 2).map((item) => ({
    ...item,
    provided: { host: { documents: { cardinality: "many" } } },
  }));
  assert.deepEqual(
    replaceProvider(collection, ["provider.local"], [], "community.cloud")
      .selected,
    ["provider.local", "community.cloud"],
  );
  assert.deepEqual(providerChoices(collection), []);
  assert.equal(providerChoices(plugins)[0].name, "ocr.backend");
});
