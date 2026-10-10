import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import {
  changeConfigField,
  changeConfigJson,
  configDraftError,
  configFields,
  configInput,
  configPointer,
  configRange,
  configRequest,
  configResetPending,
  configValue,
  draftConfigValue,
  emptyConfigDraft,
  parseConfigField,
  parseConfigJson,
  resetConfigField,
  undoConfigReset,
} from "../client/features/plugins/configurationForm.ts";

const packages = new URL("../../", import.meta.url);
const manifests = fs.readdirSync(packages).flatMap((name) => {
  const file = new URL(`${name}/manifest.json`, packages);
  return fs.existsSync(file) ? [JSON.parse(fs.readFileSync(file, "utf8"))] : [];
});
const rapidocr = manifests.find((item) => item.id === "provider.rapidocr");
const fields = configFields(rapidocr.config_schema);
const threads = fields.find((item) => item.path[0] === "intra_op_num_threads");
const retry = fields.find((item) => item.path[0] === "adaptive_retry_enabled");
const items = [{ id: rapidocr.id, state: "active", config: rapidocr.config }];

test("全部内置运行参数按清单声明生成中文标签和对应控件类型", () => {
  const configured = manifests.filter(
    (item) => Object.keys(item.config ?? {}).length,
  );
  assert.equal(configured.length, 15);
  assert.equal(
    configured.flatMap((item) => configFields(item.config_schema)).length,
    44,
  );
  for (const manifest of configured) {
    const declared = configFields(manifest.config_schema);
    assert.deepEqual(
      declared.map((field) => field.path[0]),
      Object.keys(manifest.config),
    );
    for (const field of declared) {
      assert.match(field.label, /[\u4e00-\u9fff]/);
      if (manifest.id === "sys.activity" && field.path[0] === "hidden_rules")
        assert.equal(field.kind, "json");
      else assert.notEqual(field.kind, "json");
      const value = configValue(manifest.config, field.path);
      assert.deepEqual(
        parseConfigField(field, configInput(field, value)),
        value,
      );
    }
  }
  assert.equal(fields.filter((item) => item.kind === "boolean").length, 1);
  assert.equal(
    fields.filter((item) => ["integer", "number"].includes(item.kind)).length,
    10,
  );
});

test("字段修改只发送 set，其他字段和扩展值继续继承", () => {
  const base = { ...rapidocr.config, extension: { untouched: ["保留"] } };
  const draft = changeConfigField(emptyConfigDraft(), threads, { text: "4" });
  assert.deepEqual(configRequest(items, { [rapidocr.id]: draft }), {
    configs: {},
    config_edits: [
      { instance: rapidocr.id, operation: "set", path: threads.path, value: 4 },
    ],
  });
  const projected = draftConfigValue(base, draft);
  assert.equal(projected.intra_op_num_threads, 4);
  assert.equal(projected.extension, base.extension);
  assert.equal(base.intra_op_num_threads, 2);
  assert.equal(configRequest(items, {}).config_edits.length, 0);
});

test("false、枚举值及显式 null 保持各自类型", () => {
  let draft = changeConfigField(emptyConfigDraft(), retry, { text: "false" });
  assert.equal(draft.edits[0].value, false);
  const [choice, name] = configFields({
    properties: {
      choice: { enum: [false, 0, "", null] },
      name: { anyOf: [{ type: "string" }, { type: "null" }] },
    },
  });
  for (const option of choice.schema.enum) {
    assert.deepEqual(
      parseConfigField(choice, configInput(choice, option)),
      option,
    );
  }
  assert.equal(parseConfigField(name, { text: "" }), "");
  draft = changeConfigField(draft, name, { text: "", nullValue: true });
  assert.equal(draft.edits.at(-1).value, null);
  assert.equal(configValue({}, ["name"]), undefined);
  assert.throws(
    () => parseConfigField(threads, { text: "", nullValue: true }),
    /不接受空值/,
  );
});

test("无效数值保留原始输入并阻止发送，修正后解除错误", () => {
  let draft = emptyConfigDraft();
  for (const text of [
    "",
    " ",
    "1e",
    "1e999",
    "Infinity",
    "NaN",
    "0x10",
    "1.5",
    "0",
    "17",
  ]) {
    draft = changeConfigField(draft, threads, { text });
    assert.equal(draft.fields[threads.pointer].text, text);
    assert.ok(configDraftError(draft));
    assert.throws(() => configRequest(items, { [rapidocr.id]: draft }));
  }
  draft = changeConfigField(draft, threads, { text: "8" });
  assert.equal(configDraftError(draft), "");
  assert.equal(
    configRequest(items, { [rapidocr.id]: draft }).config_edits[0].value,
    8,
  );
});

test("单项重置保留其他编辑且不发送默认字面量，撤销保留原值", () => {
  let draft = changeConfigField(emptyConfigDraft(), threads, { text: "4" });
  draft = changeConfigField(draft, retry, { text: "false" });
  draft = resetConfigField(draft, threads.path);
  assert.equal(draft.fields[threads.pointer], undefined);
  assert.ok(configResetPending(draft, threads.path));
  assert.equal(configResetPending(draft, retry.path), false);
  assert.deepEqual(
    configRequest(items, { [rapidocr.id]: draft }).config_edits,
    [
      {
        instance: rapidocr.id,
        operation: "set",
        path: retry.path,
        value: false,
      },
      { instance: rapidocr.id, operation: "reset", path: threads.path },
    ],
  );
  draft = undoConfigReset(draft, threads.path);
  assert.equal(configResetPending(draft, threads.path), false);
  assert.equal(
    draftConfigValue(rapidocr.config, draft).intra_op_num_threads,
    2,
  );
  assert.equal(draft.edits.length, 1);
});

test("全部重置清理无效 JSON 和字段输入，后续字段修改覆盖其重置", () => {
  let draft = changeConfigJson("{");
  draft = changeConfigField(draft, threads, { text: "" });
  draft = resetConfigField(draft, []);
  assert.equal(configDraftError(draft), "");
  assert.equal(draft.json, undefined);
  assert.deepEqual(draft.fields, {});
  assert.ok(configResetPending(draft, threads.path));
  assert.deepEqual(
    configRequest(items, { [rapidocr.id]: draft }).config_edits,
    [{ instance: rapidocr.id, operation: "reset", path: [] }],
  );
  draft = changeConfigField(draft, threads, { text: "6" });
  assert.equal(configResetPending(draft, threads.path), false);
  assert.equal(configResetPending(draft, retry.path), true);
});

test("高级 JSON 明确替换整份配置，新实例提交完整初值", () => {
  const draft = changeConfigJson(
    '{"intra_op_num_threads": 3, "extension": null}',
  );
  assert.deepEqual(configRequest(items, { [rapidocr.id]: draft }), {
    configs: { [rapidocr.id]: { intra_op_num_threads: 3, extension: null } },
    config_edits: [],
  });
  assert.deepEqual(
    configRequest([{ ...items[0], id: "extra", state: "待应用" }], {}).configs,
    { extra: rapidocr.config },
  );
  for (const text of ["[]", "null", "42", '{"n":1e999}', '{"n":[1e999]}'])
    assert.throws(() => parseConfigJson(text));
  assert.deepEqual(parseConfigJson('{"text":"", "flag":false}'), {
    text: "",
    flag: false,
  });
});

test("嵌套路径及特殊键保留未知同级值，重置父级清除后代输入", () => {
  const [nested] = configFields({
    properties: {
      "a/b": { type: "object", properties: { "~child": { type: "integer" } } },
    },
  });
  assert.equal(nested.pointer, "/a~1b/~0child");
  assert.equal(configPointer([]), "/");
  const base = { "a/b": { "~child": 1, extra: "保留" } };
  let draft = changeConfigField(emptyConfigDraft(), nested, { text: "7" });
  assert.deepEqual(draftConfigValue(base, draft), {
    "a/b": { "~child": 7, extra: "保留" },
  });
  draft = resetConfigField(draft, ["a/b"]);
  assert.deepEqual(draft.fields, {});
  assert.deepEqual(draft.edits, [{ operation: "reset", path: ["a/b"] }]);
  const [prototype] = configFields(
    JSON.parse('{"properties":{"__proto__":{"type":"string"}}}'),
  );
  const safe = draftConfigValue(
    {},
    changeConfigField(emptyConfigDraft(), prototype, { text: "自有字段" }),
  );
  assert.equal(configValue(safe, ["__proto__"]), "自有字段");
  assert.equal(Object.getPrototypeOf(safe), Object.prototype);
  assert.equal(configValue({}, ["__proto__"]), undefined);
});

test("本地引用支持空值，复杂联合和循环引用退回 JSON 控件", () => {
  const schema = {
    $defs: {
      count: { type: "integer", minimum: 2 },
      loop: { $ref: "#/$defs/loop" },
      recursive: { anyOf: [{ $ref: "#/$defs/recursive" }, { type: "null" }] },
    },
    properties: {
      count: { anyOf: [{ $ref: "#/$defs/count" }, { type: "null" }] },
      loop: { $ref: "#/$defs/loop" },
      recursive: { $ref: "#/$defs/recursive" },
      remote: { $ref: "https://example.invalid/schema" },
      mixed: { type: ["integer", "string"] },
      constant: { const: false },
    },
  };
  const [count, ...other] = configFields(schema);
  assert.equal(count.kind, "integer");
  assert.equal(count.nullable, true);
  assert.throws(() => parseConfigField(count, { text: "1" }), /不得小于/);
  assert.deepEqual(
    other.map((item) => item.kind),
    ["json", "json", "json", "json", "enum"],
  );
  assert.equal(parseConfigField(other.at(-1), { text: "false" }), false);
});

test("数值、字符串及复杂项的明确约束在本地检查", () => {
  const [number, text, array, object] = configFields({
    properties: {
      number: {
        type: "number",
        exclusiveMinimum: 0,
        exclusiveMaximum: 2,
        multipleOf: 0.1,
      },
      text: {
        type: "string",
        minLength: 1,
        maxLength: 2,
        pattern: "^\\p{L}+$",
      },
      array: { type: "array" },
      object: { type: "object" },
    },
  });
  assert.equal(parseConfigField(number, { text: ".3" }), 0.3);
  for (const value of ["0", "2", ".31"])
    assert.throws(() => parseConfigField(number, { text: value }));
  assert.equal(configRange(number.schema), "> 0 · < 2");
  assert.equal(configRange({ minimum: 1, exclusiveMaximum: 9 }), "≥ 1 · < 9");
  const validText = {
    ...text,
    schema: { type: "string", minLength: 1, maxLength: 2, pattern: "^[a-z]+$" },
  };
  assert.equal(parseConfigField(validText, { text: "ab" }), "ab");
  for (const value of ["", "abc", "12"])
    assert.throws(() => parseConfigField(validText, { text: value }));
  assert.deepEqual(parseConfigField(array, { text: "[]" }), []);
  assert.throws(() => parseConfigField(array, { text: "{}" }));
  assert.throws(() => parseConfigField(object, { text: "null" }));
});
