import { test } from "node:test";
import assert from "node:assert/strict";
import {
  syncHonorDocument,
  syncHonorResume,
} from "../src/features/honors/sync.ts";
import { emptyHonor, HONOR_FIELDS } from "../src/features/honors/fields.ts";
import {
  honorFieldValue,
  honorFieldHidden,
  newHonorEntry,
} from "../src/features/honors/entry.ts";
import { newDocument, newEntry } from "../src/features/profile/document.ts";
import {
  sameComposition,
  isCurrentExport,
} from "../src/features/resumes/composition.ts";

/** 完整已核对资料；与个人数据库无关 */
function source() {
  return {
    id: "linked",
    version: 2,
    reviewed: true,
    fields: {
      ...emptyHonor(),
      name: "共享证书",
      date: "2026-09",
      award: "一等奖",
      level: "省级",
      issuer: "共享单位",
      recipient: "共享团队",
      certificate_number: "DEMO-002",
      category: "竞赛获奖",
      description: "单独保存的说明",
    },
  };
}

test("existing linked honors recover all library fields without changing layout or drafts", /* 旧条目补齐缺失信息并拆开原来混入的级别且不覆盖未保存的其他资料 */ () => {
  const document = newDocument();
  document.personal.name = "姓名草稿";
  const legacy = {
    ...newEntry(),
    id: "honor:linked",
    title: "旧名称 · 一等奖",
    details: "省级\n旧说明",
    hidden_fields: ["subtitle", "details"],
    visible: false,
  };
  legacy.custom_fields = Array.from(
    { length: 20 },
    /* 保留已填满的二十项自定义资料 */ (_, index) => ({
      id: `note-${index}`,
      label: "备注",
      value: `${index}`,
      visible: index % 2 === 0,
    }),
  );
  const section = document.sections[4];
  section.title = "改名后的栏目";
  section.entries = [newEntry(), legacy];
  const original = structuredClone(document);
  const synced = syncHonorDocument(document, [source()]);
  const entry = synced.sections[4].entries[1];
  for (const field of HONOR_FIELDS)
    assert.equal(honorFieldValue(entry, field.key), source().fields[field.key]);
  assert.equal(entry.visible, false);
  assert.deepEqual(entry.hidden_fields, legacy.hidden_fields);
  assert.deepEqual(entry.custom_fields.slice(0, 20), legacy.custom_fields);
  assert.equal(entry.custom_fields.length, 25);
  assert.equal(honorFieldHidden(entry, "award"), true);
  assert.equal(synced.personal.name, "姓名草稿");
  assert.equal(synced.sections[4].title, section.title);
  assert.equal(synced.sections[4].entries[0], section.entries[0]);
  assert.deepEqual(document, original);
  assert.equal(syncHonorDocument(synced, [source()]), synced);
});

test("confirmed source changes and clearing fields update every selected resume and invalidate old exports", /* 来回切换缓存简历仍读当前资料；清空也能同步且各方案保留不同显隐 */ () => {
  const originalSource = source();
  const document = newDocument();
  document.sections[3].entries = [
    newHonorEntry(originalSource.fields, "honor:linked"),
  ];
  const resume = {
    id: "resume",
    name: "简历",
    version: 7,
    template_id: null,
    items: [],
    document,
  };
  const other = structuredClone(resume);
  other.id = "another";
  other.document.sections[3].entries[0].hidden_fields = ["period"];
  const changed = {
    ...originalSource,
    version: 3,
    fields: {
      ...originalSource.fields,
      name: "更新后的证书",
      award: "",
      description: "",
    },
  };
  const synced = syncHonorResume(resume, [changed]);
  const second = syncHonorResume(other, [changed]);
  assert.equal(
    synced.document.sections[3].entries[0].title,
    changed.fields.name,
  );
  assert.equal(
    honorFieldValue(synced.document.sections[3].entries[0], "award"),
    "",
  );
  assert.equal(synced.document.sections[3].entries[0].details, "");
  assert.deepEqual(second.document.sections[3].entries[0].hidden_fields, [
    "period",
  ]);
  assert.equal(synced.version, 7);
  assert.equal(
    sameComposition(synced, syncHonorResume(resume, [changed])),
    true,
  );
  assert.equal(
    isCurrentExport({ resume_id: resume.id, manifest: { resume } }, synced),
    false,
  );
  assert.equal(syncHonorResume(synced, []), synced);
});

test("unreviewed suggestions, same-name records and manual entries cannot overwrite linked content", /* 同名不同标识、人工条目和未核对识别结果都不会被误关联 */ () => {
  const document = newDocument();
  document.sections[3].entries = [
    newHonorEntry(source().fields, "honor:linked"),
    newHonorEntry(source().fields),
  ];
  assert.equal(
    syncHonorDocument(document, [
      {
        ...source(),
        reviewed: false,
        fields: { ...source().fields, name: "未核对名称" },
      },
    ]),
    document,
  );
  assert.equal(
    syncHonorDocument(document, [{ ...source(), id: "different" }]),
    document,
  );
  const synced = syncHonorDocument(document, [
    { ...source(), fields: { ...source().fields, name: "新名称" } },
  ]);
  assert.equal(synced.sections[3].entries[1], document.sections[3].entries[1]);
  assert.equal(syncHonorDocument(null, [source()]), null);
});
