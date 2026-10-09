import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createClientServices,
  remoteProvider,
} from "../src/plugins/services.ts";

test("客户端只消费声明的提供方，卸载后依赖不能继续取得失效服务", () => {
  const services = createClientServices();
  const provider = {
    id: "example.provider",
    provides: { math: { version: "1.0.0" } },
  };
  const consumer = {
    id: "example.consumer",
    bindings: { client: { math: { owners: [provider.id], many: false } } },
  };
  assert.throws(() => services.require(consumer, "math"), /尚未激活/);
  assert.throws(
    () => services.provide(provider, "math", {}, "2.0.0"),
    /未声明/,
  );
  const value = { double: (x) => x * 2 };
  const dispose = services.provide(provider, "math", value, "1.0.0");
  services.validate(provider);
  assert.equal(services.require(consumer, "math").double(21), 42);
  assert.throws(() => services.require(consumer, "private"), /未声明/);
  dispose();
  assert.throws(() => services.require(consumer, "math"), /尚未激活/);
});

test("客户端集合按锁定顺序返回且不能修改注册集合", () => {
  const services = createClientServices();
  for (const id of ["two", "one"])
    services.provide(
      { id, provides: { engine: { version: "1.0.0" } } },
      "engine",
      id,
      "1.0.0",
    );
  const value = services.require(
    {
      id: "user",
      bindings: { client: { engine: { owners: ["one", "two"], many: true } } },
    },
    "engine",
  );
  assert.deepEqual(value, ["one", "two"]);
  assert.throws(() => value.push("three"));
});

test("远端集合调用必须明确选择已声明的提供方", () => {
  const item = {
    id: "consumer",
    bindings: { remote: { engine: { owners: ["one", "two"], many: true } } },
  };
  assert.throws(() => remoteProvider(item, "engine"), /选择/);
  assert.throws(() => remoteProvider(item, "engine", "unknown"), /选择/);
  assert.equal(remoteProvider(item, "engine", "two"), "two");
  assert.throws(() => remoteProvider(item, "private", "one"), /未声明/);
});
