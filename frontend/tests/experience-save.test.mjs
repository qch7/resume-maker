import assert from "node:assert/strict";
import { test } from "node:test";
import { newDocument } from "../src/shared/resume/document.ts";
import { applyExperienceRevision } from "../../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/experienceSave.ts";

/** 构造包含固定项目引用、独立简历显示设置的合成资料 */
function fixture() {
  const document = newDocument();
  document.personal.name = "测试同学";
  document.project_visibility = {
    project: {
      fields: { role: false, stack: true },
      custom_fields: { link: false },
      order: ["highlights", "description", "role"],
    },
  };
  const submitted = {
    id: "resume",
    name: "原方案",
    template_id: "template",
    version: 2,
    document,
    items: [
      {
        project_id: "project",
        revision_id: "old",
        highlight_ids: ["a", "b"],
      },
      {
        project_id: "other",
        revision_id: "other-version",
        highlight_ids: ["other-point"],
      },
    ],
  };
  return {
    submitted,
    current: structuredClone(submitted),
    saved: revision("saved", ["c", "new", "a"]),
  };
}

/** 创建带稳定亮点标识的不可变经历版本 */
function revision(id, ids) {
  return {
    id,
    project_id: "project",
    number: id === "old" ? 1 : 2,
    parent_id: id === "old" ? null : "old",
    snapshot_id: null,
    origin: "manual",
    note: "",
    created_at: "2026-10-15T00:00:00Z",
    branch_id: "main",
    branch_name: "主分支",
    content: {
      title: "测试项目",
      period: "2026",
      role: "开发",
      stack: ["TypeScript"],
      description: "已核实的项目描述",
      highlights: ids.map((point) => ({
        id: point,
        title: `亮点 ${point}`,
        text: `正文 ${point}`,
        evidence: [],
      })),
    },
  };
}

test("保存后应用返回版本并保留最新亮点选择、其他资料及显隐", () => {
  const { submitted, current, saved } = fixture();
  current.name = "请求后的方案名";
  current.template_id = "new-template";
  current.document.personal.name = "请求后的姓名";
  current.document.project_visibility.project.fields.role = true;
  current.items[0].highlight_ids = ["removed", "a", "new", "c"];
  current.items[1].highlight_ids = [];
  const before = structuredClone({
    submitted,
    current,
    saved,
  });
  const applied = applyExperienceRevision(current, submitted, saved);
  assert.equal(applied.items[0].revision_id, "saved");
  assert.deepEqual(applied.items[0].highlight_ids, ["c", "new", "a"]);
  assert.deepEqual(applied, {
    ...current,
    items: [
      {
        ...current.items[0],
        revision_id: "saved",
        highlight_ids: ["c", "new", "a"],
      },
      current.items[1],
    ],
  });
  assert.equal(applied.document, current.document);
  assert.equal(applied.items[1], current.items[1]);
  assert.deepEqual({ submitted, current, saved }, before);
});

test("切换已保存方案后迟到版本不能应用到当前方案", () => {
  const { submitted, current, saved } = fixture();
  current.id = "other-resume";
  assert.equal(applyExperienceRevision(current, submitted, saved), current);
});

test("未保存方案按独立草稿身份应用，其他恢复稿及无身份草稿保持原样", () => {
  const { submitted, current, saved } = fixture();
  submitted.id = "";
  current.id = "";
  submitted.draft_id = "first-draft";
  current.draft_id = "first-draft";
  const applied = applyExperienceRevision(current, submitted, saved);
  assert.equal(applied.id, "");
  assert.equal(applied.draft_id, "first-draft");
  assert.equal(applied.items[0].revision_id, "saved");
  current.draft_id = "recovered-draft";
  assert.equal(applyExperienceRevision(current, submitted, saved), current);
  delete current.draft_id;
  delete submitted.draft_id;
  assert.equal(applyExperienceRevision(current, submitted, saved), current);
});

test("请求期间移除项目或改用其他版本时不恢复旧引用", () => {
  const { submitted, current, saved } = fixture();
  const removed = { ...current, items: [current.items[1]] };
  assert.equal(applyExperienceRevision(removed, submitted, saved), removed);
  const switched = structuredClone(current);
  switched.items[0].revision_id = "chosen-later";
  assert.equal(applyExperienceRevision(switched, submitted, saved), switched);
  const withoutProject = { ...submitted, items: [submitted.items[1]] };
  assert.equal(
    applyExperienceRevision(current, withoutProject, saved),
    current,
  );
});

test("首次加入按返回版本全选亮点并保留其他项目顺序", () => {
  const { submitted, current, saved } = fixture();
  submitted.items.shift();
  current.items.shift();
  const applied = applyExperienceRevision(current, submitted, saved);
  assert.equal(applied.items[0], current.items[0]);
  assert.deepEqual(applied.items[1], {
    project_id: "project",
    revision_id: "saved",
    highlight_ids: ["c", "new", "a"],
  });
});

test("已有亮点全部隐藏时新版本仍保持全部隐藏", () => {
  const { submitted, current, saved } = fixture();
  current.items[0].highlight_ids = [];
  const applied = applyExperienceRevision(current, submitted, saved);
  assert.deepEqual(applied.items[0].highlight_ids, []);
  assert.equal(applied.document, current.document);
});

test("引用旧空版本时仍保留草稿中选择的新增亮点子集及全部隐藏状态", () => {
  for (const selected of [["new"], []]) {
    const { submitted, current, saved } = fixture();
    submitted.items[0].revision_id = "empty";
    submitted.items[0].highlight_ids = [];
    current.items[0] = {
      ...submitted.items[0],
      highlight_ids: selected,
    };
    const applied = applyExperienceRevision(current, submitted, saved);
    assert.equal(applied.items[0].revision_id, saved.id);
    assert.deepEqual(applied.items[0].highlight_ids, selected);
  }
});
