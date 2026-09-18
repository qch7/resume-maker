import { test } from "node:test";
import assert from "node:assert/strict";
import {
  fieldChanged,
  editHighlightText,
} from "../src/features/experiences/changes.ts";
import {
  experienceContent,
  separateMetaVisibility,
} from "../src/features/experiences/visibility.ts";
import {
  projectBodyOrder,
  restoreBodyOrder,
} from "../src/features/experiences/bodyOrder.ts";
import { buildLivePreview } from "../src/features/resumes/livePreview.ts";
import { newDocument } from "../src/features/profile/document.ts";

/** 包含核实证据、自定义信息和两条亮点，覆盖多个编辑器共同变化。 */
function fixture() {
  return {
    title: "项目",
    period: "2026",
    role: "开发",
    stack: ["Python"],
    description: "原描述",
    custom_fields: [
      { id: "link", label: "链接", value: "example.test", visible: true },
    ],
    highlights: [
      {
        id: "one",
        title: "亮点一",
        text: "原正文",
        evidence: [
          {
            source: "source-0",
            path: "a.py",
            line_start: 1,
            line_end: 2,
            quote: "code",
            status: "code",
          },
        ],
      },
      { id: "two", title: "亮点二", text: "第二条", evidence: [] },
    ],
  };
}

test("默认、版本和旧简历顺序调回原位后均无改动", /* 真实位移需要提交，往返移动恢复原始表示，预览无需提交。 */ () => {
  for (const kind of ["default", "version", "legacy"]) {
    const base = fixture();
    const settings =
      kind === "legacy"
        ? {
            order: [
              "custom:link",
              "role",
              "stack",
              "description",
              "highlights",
            ],
          }
        : {};
    if (kind === "version")
      base.body_order = [
        "description",
        "highlights",
        "role",
        "stack",
        "custom:link",
      ];
    const initial = projectBodyOrder(base, settings);
    const moved = {
      ...base,
      body_order: [initial[1], initial[0], ...initial.slice(2)],
    };
    assert.equal(fieldChanged(moved, base, "meta", settings), true);
    const restored = restoreBodyOrder(
      { ...moved, body_order: initial },
      base,
      settings,
    );
    assert.deepEqual(restored.body_order, base.body_order ?? null);
    assert.equal(fieldChanged(restored, base, "meta", settings), false);
    assert.equal(
      experienceContent(restored, settings),
      experienceContent(base, settings),
    );
    const document = {
      ...newDocument(),
      project_visibility: { project: settings },
    };
    const draft = {
      document,
      items: [
        {
          project_id: "project",
          revision_id: "r1",
          highlight_ids: ["one", "two"],
        },
      ],
    };
    const revisions = {
      r1: { id: "r1", project_id: "project", content: base },
    };
    assert.equal(
      buildLivePreview(draft, revisions, { r1: restored }, "project", "r1")
        .changed,
      false,
    );
    const oldNoop = separateMetaVisibility(
      base,
      { ...base, body_order: initial },
      settings,
    );
    assert.equal(oldNoop.contentChanged, false);
    assert.deepEqual(oldNoop.meta.body_order, base.body_order ?? null);
  }
});

test("基本信息、自定义信息、亮点正文和顺序都按当前值比较", /* 改回一项只消除该项差异，其他未还原输入仍须提交。 */ () => {
  const base = fixture();
  for (const key of ["title", "period", "role", "description"]) {
    assert.equal(
      fieldChanged({ ...base, [key]: "临时文字" }, base, "meta"),
      true,
    );
    assert.equal(
      fieldChanged({ ...base, [key]: base[key] }, base, "meta"),
      false,
    );
  }
  const working = {
    ...base,
    custom_fields: [{ ...base.custom_fields[0], value: "changed.test" }],
  };
  assert.equal(fieldChanged(working, base, "meta"), true);
  working.custom_fields = structuredClone(base.custom_fields);
  assert.equal(fieldChanged(working, base, "meta"), false);
  assert.equal(fieldChanged(["two", "one"], base, "order"), true);
  assert.equal(fieldChanged(["one", "two"], base, "order"), false);
  const changed = editHighlightText(
    base.highlights[0],
    "改过的正文",
    base.highlights[0],
  );
  assert.equal(changed.evidence[0].status, "unverified");
  assert.equal(fieldChanged(changed, base, "highlight:one"), true);
  const reverted = editHighlightText(changed, "原正文", base.highlights[0]);
  assert.equal(reverted.evidence[0].status, "code");
  assert.equal(fieldChanged(reverted, base, "highlight:one"), false);
  assert.notEqual(
    experienceContent({
      ...base,
      role: "其他改动",
      highlights: [reverted, base.highlights[1]],
    }),
    experienceContent(base),
  );
  const added = { ...changed, id: "new", text: "新增亮点" };
  assert.equal(fieldChanged(added, base, "highlight:new"), true);
});
