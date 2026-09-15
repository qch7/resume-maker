import { test } from "node:test";
import assert from "node:assert/strict";
import {
  reviewProblems,
  reviewProblemSummary,
} from "../src/features/templates/review.ts";

/** 构造没有结构错误的检查结果，按用例加入实际阻止使用的原因。 */
function review(overrides = {}) {
  return {
    ready: false,
    errors: [],
    issues: [],
    missing: [],
    unresolved: [],
    ...overrides,
  };
}

test("缺少所在地时直接显示中文原因", /* 复现识别完成却无法试填的实际反馈缺口。 */ () => {
  const problems = reviewProblems(review({ missing: ["personal.location"] }));
  assert.deepEqual(problems, [
    { message: "“所在地”尚未安排填写位置", nodes: [] },
  ]);
  assert.equal(reviewProblemSummary(problems), "“所在地”尚未安排填写位置");
});

test("空定位列表不会隐藏试填错误，重复错误保留调整入口", /* 后端试填阶段只追加 errors 时也必须展示原因。 */ () => {
  const message = "栏目边界无法生成试填";
  assert.deepEqual(reviewProblems(review({ errors: [message] })), [
    { message, nodes: [] },
  ]);
  assert.deepEqual(
    reviewProblems(
      review({
        errors: [message, "Word 试填失败"],
        issues: [{ message, nodes: ["section"] }],
      }),
    ),
    [
      { message, nodes: ["section"] },
      { message: "Word 试填失败", nodes: [] },
    ],
  );
});

test("未归类原文和图片全部计入问题数量并可定位", /* 不让相同原文或图片问题藏在折叠列表里。 */ () => {
  const problems = reviewProblems(
    review({
      missing: ["personal.custom:语言"],
      unresolved: [
        { id: "text-1", kind: "p", text: "示例经历" },
        { id: "text-2", kind: "p", text: "示例经历" },
        { id: "photo", kind: "image", text: "" },
      ],
    }),
  );
  assert.equal(problems.length, 4);
  assert.deepEqual(problems[2].nodes, ["text-2"]);
  assert.equal(problems[3].message, "图片用途尚未确认");
  assert.equal(
    reviewProblemSummary(problems),
    "“语言”尚未安排填写位置（共 4 项问题）",
  );
});

test("普通排版提醒不会阻止已通过的模板，没有原因时仍解释状态", /* 检查中的状态与真正阻止使用的问题分开呈现。 */ () => {
  assert.deepEqual(reviewProblems(null), []);
  assert.deepEqual(
    reviewProblems(review({ ready: true, notices: ["字体按原文估计"] })),
    [],
  );
  assert.equal(reviewProblemSummary([]), "");
  assert.match(reviewProblems(review())[0].message, /模板检查尚未通过/);
});
