import assert from "node:assert/strict";
import test from "node:test";
import { recoverActivePlan } from "../src/features/plugins/planRecovery.ts";

test("恢复过期普通准备计划，较新的预览和结束记录不会遮住取消入口", () => {
  const preparing = { id: "ordinary", state: "preparing", expires_at: 1 };
  const operations = [
    { id: "ended", state: "committed", expires_at: 99, package_updates: {} },
    { id: "preview", state: "planned", expires_at: 100 },
    preparing,
  ];
  assert.equal(recoverActivePlan(operations), preparing);
  assert.equal(operations[0].id, "ended");
  assert.equal(
    recoverActivePlan(operations.filter((item) => item !== preparing)).id,
    "preview",
  );
});

test("恢复各类进行中计划，不要求包更新字段，全部结束时不恢复", () => {
  for (const state of [
    "preparing",
    "validating",
    "restart-required",
    "booting",
    "applying",
  ]) {
    const plan = { id: state, state };
    assert.equal(recoverActivePlan([plan]), plan);
  }
  assert.equal(
    recoverActivePlan([
      { state: "committed" },
      { state: "cancelled" },
      { state: "failed" },
    ]),
    undefined,
  );
});
