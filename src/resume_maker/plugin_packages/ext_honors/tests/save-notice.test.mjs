import assert from "node:assert/strict";
import { test } from "node:test";
import { honorSaveNotice } from "../client/saveNotice.ts";

test("honor save notice distinguishes library, current draft and saved links", () => {
  assert.equal(honorSaveNotice(0, false), "已保存到荣誉库。");
  assert.equal(honorSaveNotice(null, false), "已保存到荣誉库。");
  assert.equal(
    honorSaveNotice(0, true),
    "已保存到荣誉库，已更新当前简历草稿。",
  );
  assert.equal(
    honorSaveNotice(2, true),
    "已保存到荣誉库，2 份关联简历会自动使用最新资料。",
  );
});
