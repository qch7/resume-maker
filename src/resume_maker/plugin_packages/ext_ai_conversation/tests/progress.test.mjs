import assert from "node:assert/strict";
import { test } from "node:test";
import { appendProgress, progressDuration } from "../client/progress.ts";

test("连续同类反馈合并，保留实际最近进展时间，阶段变化独立展示", () => {
  let entries = [];
  for (let index = 0; index < 20; index++)
    entries = appendProgress(entries, {
      kind: "activity",
      created_at: new Date(1000 * index).toISOString(),
      data: { type: "material_read", text: "正在读取脱敏源码" },
    });
  assert.equal(entries.length, 1);
  assert.equal(entries[0].count, 20);
  assert.equal(entries[0].at, 19000);
  entries = appendProgress(entries, {
    kind: "status",
    data: { text: "正在核对引用并保存证据" },
  });
  assert.equal(entries.length, 2);
  assert.equal(entries[1].count, 1);
});

test("进度细节有界且不展示推理、工具参数、未知事件及原始错误", () => {
  let entries = [];
  for (let index = 0; index < 50; index++)
    entries = appendProgress(entries, {
      kind: "activity",
      data: { type: "source_progress", text: `完成 ${index} 次工具调用` },
    });
  assert.equal(entries.length, 20);
  assert.equal(entries[0].text, "完成 30 次工具调用");
  for (const kind of ["reasoning", "thread", "tool"])
    assert.equal(
      appendProgress(entries, { kind, data: { text: "private" } }),
      entries,
    );
  assert.equal(
    appendProgress(entries, {
      kind: "activity",
      data: { type: "reasoning", text: "private" },
    }),
    entries,
  );
  const failed = appendProgress(entries, {
    kind: "error",
    data: { text: "C:/private/path" },
  });
  assert.ok(!JSON.stringify(failed).includes("private"));
});

test("等待时长来自真实时间差，异常时间不显示负数或百分比", () => {
  assert.equal(progressDuration(0, 125000), "2 分 5 秒");
  assert.equal(progressDuration(2000, 1000), "0 秒");
  assert.equal(progressDuration(0, 7000), "7 秒");
});
