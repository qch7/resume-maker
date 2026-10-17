import test from "node:test";
import assert from "node:assert/strict";
import {
  currentFitResult,
  fitResultSucceeded,
} from "../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/layoutFit.ts";

test("自动压页只发布完整输入仍一致的当前响应", async () => {
  const original = JSON.stringify([
    "resume-a",
    {
      template_id: "t1",
      document: { name: "原文" },
      items: [{ revision_id: "r1" }],
    },
  ]);
  const active = { identity: original, controller: new AbortController() };
  assert.equal(currentFitResult(active, active, original), true);
  for (const identity of [
    JSON.stringify([
      "resume-b",
      {
        template_id: "t1",
        document: { name: "原文" },
        items: [{ revision_id: "r1" }],
      },
    ]),
    JSON.stringify([
      "resume-a",
      {
        template_id: "t2",
        document: { name: "原文" },
        items: [{ revision_id: "r1" }],
      },
    ]),
    JSON.stringify([
      "resume-a",
      {
        template_id: "t1",
        document: { name: "新文" },
        items: [{ revision_id: "r1" }],
      },
    ]),
  ])
    assert.equal(currentFitResult(active, active, identity), false);
  const replacement = { identity: original, controller: new AbortController() };
  assert.equal(currentFitResult(active, replacement, original), false);
  active.controller.abort();
  await Promise.resolve();
  assert.equal(currentFitResult(active, active, original), false);
  assert.equal(currentFitResult(replacement, null, original), false);
});

test("只有实测达标状态可以采用，无法压入及缺失页数保留原设置", () => {
  for (const status of ["fit", "unchanged"]) {
    assert.equal(fitResultSucceeded({ status, pages: 1 }, 1), true);
    assert.equal(fitResultSucceeded({ status, pages: 2 }, 1), false);
    assert.equal(fitResultSucceeded({ status, pages: null }, 1), false);
    assert.equal(fitResultSucceeded({ status, pages: 0 }, 1), false);
  }
  for (const status of ["unfit", "unavailable"])
    assert.equal(fitResultSucceeded({ status, pages: 1 }, 1), false);
});
