import { test } from "node:test";
import assert from "node:assert/strict";
import { recoveryCopies } from "../src/shared/lib/recoveryCopies.ts";

test("repeated recovery keeps earlier unsent inputs and normalizes a legacy copy", /* 多次载入保留所有原稿，不覆盖旧单份副本 */ () => {
  const first = recoveryCopies("窗口甲原稿", "窗口乙原稿");
  const second = recoveryCopies(first, "窗口丙原稿");
  assert.deepEqual(second, ["窗口甲原稿", "窗口乙原稿", "窗口丙原稿"]);
  assert.equal(recoveryCopies(second, "窗口乙原稿"), second);
  assert.deepEqual(recoveryCopies(null, ""), [""]);
  assert.deepEqual(first, ["窗口甲原稿", "窗口乙原稿"]);
});
