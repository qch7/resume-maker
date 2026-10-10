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

test("新领域能力自动发现，显示声明名称并兼容未声明名称的提供方", () => {
  const providers = [
    {
      id: "speech.local",
      required: false,
      provided: {
        host: { "speech.backend": {} },
        client: { "speech.backend": { title: "语音播放器" } },
      },
    },
    {
      id: "speech.cloud",
      required: false,
      provided: {
        host: {
          "speech.backend": { cardinality: "one", title: "语音合成引擎" },
        },
        client: { "speech.backend": {} },
      },
    },
    ...["translation.local", "translation.cloud"].map((id) => ({
      id,
      required: false,
      provided: { host: { "translation.backend": { title: null } } },
    })),
    {
      id: "single.provider",
      required: false,
      provided: { host: { "single.backend": {} } },
    },
  ];
  assert.deepEqual(providerChoices(providers), [
    {
      domain: "host",
      name: "speech.backend",
      title: "语音合成引擎",
      ids: ["speech.local", "speech.cloud"],
    },
    {
      domain: "client",
      name: "speech.backend",
      title: "语音播放器",
      ids: ["speech.local", "speech.cloud"],
    },
    {
      domain: "host",
      name: "translation.backend",
      title: "translation.backend",
      ids: ["translation.local", "translation.cloud"],
    },
  ]);
});

test("跨领域替换全部冲突能力，绑定按域更新并保留集合及其他消费者", () => {
  const providers = [
    {
      id: "old.speech",
      required: false,
      provided: { host: { "speech.backend": {} } },
    },
    {
      id: "old.translation",
      required: false,
      provided: { host: { "translation.backend": {} } },
    },
    {
      id: "client.speech",
      required: false,
      provided: { client: { "speech.backend": {} } },
    },
    {
      id: "old.collection",
      required: false,
      provided: { host: { documents: { cardinality: "many" } } },
    },
    {
      id: "new.multidomain",
      required: false,
      provided: {
        host: {
          "speech.backend": {},
          "translation.backend": {},
          documents: { cardinality: "many" },
        },
      },
    },
  ];
  const instances = [
    {
      id: "consumer",
      plugin: "consumer",
      bindings: {
        host: {
          "speech.backend": "old.speech",
          "translation.backend": "old.translation",
          documents: "old.collection",
        },
        client: { "speech.backend": "client.speech" },
        remote: { "speech.backend": "old.speech" },
      },
    },
  ];
  const candidate = replaceProvider(
    providers,
    [
      "old.speech",
      "old.translation",
      "client.speech",
      "old.collection",
      "consumer",
    ],
    instances,
    "new.multidomain",
  );
  assert.deepEqual(candidate.selected, [
    "client.speech",
    "old.collection",
    "consumer",
    "new.multidomain",
  ]);
  assert.deepEqual(candidate.removed, ["old.speech", "old.translation"]);
  assert.deepEqual(candidate.instances[0].bindings, {
    host: {
      "speech.backend": "new.multidomain",
      "translation.backend": "new.multidomain",
      documents: "old.collection",
    },
    client: { "speech.backend": "client.speech" },
    remote: { "speech.backend": "new.multidomain" },
  });
  assert.equal(instances[0].bindings.host["speech.backend"], "old.speech");
});
