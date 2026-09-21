import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  addHonors,
  emptyHonor,
  hasHonor,
  matchesHonor,
  removeHonor,
} from "../src/features/honors/model.ts";
import {
  filledEntries,
  newDocument,
  newEntry,
} from "../src/features/profile/document.ts";
import {
  honorFieldHidden,
  honorFieldValue,
  isHonorEntry,
  isHonorSection,
  nameAndDateOnly,
  newHonorEntry,
  updateHonorField,
  entryWithHonorFields,
  honorFieldsFromEntry,
} from "../src/features/honors/entry.ts";
import { HONOR_FIELDS } from "../src/features/honors/fields.ts";
import { entryComposition, findEntry } from "../src/features/profile/entry.ts";
import { sameSectionEntry } from "../src/features/profile/comparison.ts";
import { syncHonorDocument } from "../src/features/honors/sync.ts";

test("removing a linked honor preserves same-name entries, sections and other resume data", /* 自定义栏目也可移除，原始简历、同名资料及库中来源保持不变 */ () => {
  const source = honor();
  const sourceBefore = structuredClone(source);
  const document = addHonors(newDocument(), [source, honor("other")], "skills");
  document.personal.name = "尚未保存的姓名";
  const section = document.sections.find(
    /* 模拟荣誉被加入隐藏的自定义栏目 */ (item) => item.id === "skills",
  );
  section.title = "自定义成果";
  section.visible = false;
  const manual = newHonorEntry(source.fields);
  section.entries.push(manual);
  const before = structuredClone(document);
  const removed = removeHonor(document, source.id);
  const retained = removed.sections.find(
    /* 栏目自身保留原来的名称和显隐设置 */ (item) => item.id === section.id,
  );
  assert.equal(hasHonor(removed, source.id), false);
  assert.equal(hasHonor(removed, "other"), true);
  assert.deepEqual(retained, {
    ...section,
    entries: [section.entries[1], manual],
  });
  assert.equal(removed.personal, document.personal);
  assert.equal(removed.sections.length, document.sections.length);
  assert.equal(removed.sections[0], document.sections[0]);
  assert.deepEqual(document, before);
  assert.deepEqual(source, sourceBefore);
  assert.equal(removeHonor(removed, source.id), removed);
});

test("removed honors stay absent during source sync and can be added again", /* 来源更新不恢复已移除引用，重新加入时采用最新内容 */ () => {
  const source = honor();
  const document = addHonors(newDocument(), [source]);
  const removed = removeHonor(document, source.id);
  source.fields.name = "重新核对的证书";
  assert.equal(syncHonorDocument(removed, [source]), removed);
  const section = removed.sections.find(
    /* 移除最后一条后保留空栏目，便于重新加入 */ (item) => item.id === "honors",
  );
  assert.deepEqual(section.entries, []);
  const added = addHonors(removed, [source]);
  assert.equal(hasHonor(added, source.id), true);
  assert.equal(
    added.sections.find(
      /* 重新加入到原来的荣誉栏目 */ (item) => item.id === section.id,
    ).entries[0].title,
    source.fields.name,
  );
  assert.equal(addHonors(added, [source]), added);
});

test("unified honor editing preserves resume preferences and separates source data", /* 内容双向对应，显隐及自定义备注不进入共享荣誉 */ () => {
  const source = honor();
  const existing = newHonorEntry(source.fields, `honor:${source.id}`);
  existing.visible = false;
  existing.custom_fields.push({
    id: "note",
    label: "备注",
    value: "本简历专用",
    visible: true,
  });
  const before = structuredClone(existing);
  const latest = { ...source.fields, name: "来源的新名称", date: "2026-09" };
  let edited = entryWithHonorFields(existing, latest);
  edited = updateHonorField(edited, "name", { value: "统一表单修改" });
  edited = updateHonorField(edited, "issuer", { hidden: false });
  assert.deepEqual(honorFieldsFromEntry(edited), {
    ...latest,
    name: "统一表单修改",
  });
  assert.equal(edited.visible, false);
  assert.equal(honorFieldHidden(edited, "issuer"), false);
  assert.deepEqual(edited.custom_fields.at(-1), before.custom_fields.at(-1));
  assert.deepEqual(existing, before);
});

/** 生成不依赖服务端或个人资料的已核对荣誉 */
function honor(id = "sample") {
  return {
    id,
    status: "ready",
    reviewed: true,
    fields: {
      ...emptyHonor(),
      name: "示例竞赛",
      award: "一等奖",
      issuer: "示例组委会",
      date: "2026-06",
      certificate_number: "DEMO-001",
      level: "省级",
      recipient: "示例团队",
      category: "竞赛获奖",
      description: "示例获奖项目\n第二行补充说明",
    },
    attachment: null,
  };
}

test("adding honors keeps initial values immutable until a source update is received", /* 验证跨栏目去重及对象隔离，库更新通过专用同步入口采用 */ () => {
  const original = newDocument();
  const item = honor();
  const composed = addHonors(original, [item]);
  const entry = composed.sections.find(
    /* 查找目标栏目 */ (section) => section.id === "honors",
  ).entries[0];
  assert.equal(entry.title, "示例竞赛");
  assert.equal(entry.subtitle, "示例组委会");
  assert.equal(entry.period, "2026-06");
  assert.equal(hasHonor(composed, item.id), true);
  assert.equal(hasHonor(original, item.id), false);
  assert.equal(addHonors(composed, [item]), composed);
  item.fields.name = "修改后的名称";
  assert.equal(entry.title, "示例竞赛");
  assert.equal(
    original.sections.find(
      /* 原始草稿保持不变 */ (section) => section.id === "honors",
    ).entries.length,
    0,
  );
});

test("all honor fields keep their meaning while only name and date appear by default", /* 所有库字段无损复制，奖项、级别和说明不再合并 */ () => {
  const item = honor();
  const composed = addHonors(newDocument(), [item]);
  const section = composed.sections.find(
    /* 读取荣誉栏目的完整保存资料和成品副本 */ (section) =>
      section.id === "honors",
  );
  const entry = section.entries[0];
  assert.deepEqual(
    entry,
    JSON.parse(
      readFileSync(
        new URL("../../tests/fixtures/honor-entry.json", import.meta.url),
        "utf8",
      ),
    ),
  );
  for (const field of HONOR_FIELDS) {
    assert.equal(honorFieldValue(entry, field.key), item.fields[field.key]);
    assert.equal(
      honorFieldHidden(entry, field.key),
      !["name", "date"].includes(field.key),
    );
  }
  const [displayed] = filledEntries(section);
  assert.deepEqual(
    [
      displayed.title,
      displayed.period,
      displayed.subtitle,
      displayed.details,
      displayed.custom_fields,
    ],
    ["示例竞赛", "2026-06", "", "", []],
  );
  assert.equal(entry.details, item.fields.description);
  item.fields.award = "后续改奖项";
  assert.equal(honorFieldValue(entry, "award"), "一等奖");
  const longName = { ...item.fields, name: "证".repeat(300) };
  assert.equal(newHonorEntry(longName).title, longName.name);
  assert.equal(newHonorEntry(longName).details, longName.description);
});

test("manual and relocated honor entries use the same fields without changing other sections", /* 荣誉字段在手工录入、换栏目和改名后仍能识别 */ () => {
  const sections = newDocument().sections;
  const honors = sections.find(
    /* 默认荣誉栏目 */ (section) => section.id === "honors",
  );
  const skills = sections.find(
    /* 普通技能栏目 */ (section) => section.id === "skills",
  );
  const entry = newHonorEntry();
  assert.equal(isHonorSection(honors), true);
  assert.equal(
    isHonorSection({ ...honors, id: "custom", title: "职业资格证书" }),
    true,
  );
  assert.equal(isHonorEntry(entry, { ...skills, title: "我的成果" }), true);
  assert.equal(isHonorEntry(newEntry(), skills), false);
  assert.deepEqual(entry.hidden_fields, ["subtitle", "details"]);
  assert.equal(honorFieldHidden(entry, "category"), true);
  assert.deepEqual(filledEntries({ ...honors, entries: [entry] }), []);
  const renamed = { ...honors, title: "我的成果", entries: [entry] };
  assert.equal(isHonorEntry(entry, renamed), true);
  assert.equal(isHonorSection({ ...honors, kind: "education" }), false);
});

test("optional honor edits and visibility survive a single-entry save without touching other drafts", /* 单条保存保留可选资料、显示设置和其他草稿 */ () => {
  const saved = {
    id: "resume",
    name: "示例方案",
    version: 1,
    template_id: null,
    items: [],
    document: addHonors(newDocument(), [honor()]),
  };
  const draft = structuredClone(saved);
  draft.document.personal.name = "尚未保存姓名";
  const section = draft.document.sections.find(
    /* 读取待编辑的荣誉栏目 */ (section) => section.id === "honors",
  );
  let entry = updateHonorField(section.entries[0], "award", {
    value: "二等奖",
    hidden: false,
  });
  entry = updateHonorField(entry, "issuer", {
    value: "新颁发单位",
    hidden: false,
  });
  entry = updateHonorField(entry, "description", { value: "新项目说明" });
  section.entries[0] = entry;
  assert.equal(
    sameSectionEntry(entry, findEntry(saved.document, "honors", entry.id)),
    false,
  );
  const submitted = entryComposition(draft, saved, "honors", entry.id);
  const restored = JSON.parse(JSON.stringify(submitted));
  const stored = findEntry(restored.document, "honors", entry.id);
  assert.equal(sameSectionEntry(entry, stored), true);
  assert.equal(restored.document.personal.name, "");
  assert.equal(honorFieldValue(stored, "award"), "二等奖");
  assert.equal(honorFieldHidden(stored, "award"), false);
  assert.equal(honorFieldValue(stored, "description"), "新项目说明");
  assert.equal(honorFieldHidden(stored, "description"), true);
  const [displayed] = filledEntries({ ...section, entries: [stored] });
  assert.equal(displayed.subtitle, "新颁发单位");
  assert.deepEqual(
    displayed.custom_fields.map(
      /* 只有用户打开的可选字段参与排版 */ (field) => [
        field.label,
        field.value,
      ],
    ),
    [["奖项", "二等奖"]],
  );
  assert.equal(
    honorFieldValue(findEntry(saved.document, "honors", entry.id), "award"),
    "一等奖",
  );
});

test("existing entries can adopt name and date display without losing text or custom data", /* 已有条目一键收起附加信息，恢复后原文仍然存在 */ () => {
  const existing = {
    ...newEntry(),
    id: "honor:existing",
    title: "已有证书名称",
    subtitle: "已有颁发单位",
    period: "2025",
    details: "已有说明",
    hidden_fields: ["title"],
    custom_fields: [
      { id: "user-note", label: "备注", value: "保留我", visible: true },
    ],
  };
  const updated = nameAndDateOnly(existing);
  assert.deepEqual(updated.hidden_fields, ["subtitle", "details"]);
  assert.equal(updated.custom_fields[0].visible, false);
  assert.equal(existing.custom_fields[0].visible, true);
  assert.equal(updated.subtitle, existing.subtitle);
  assert.equal(updated.details, existing.details);
  assert.equal(honorFieldValue(updated, "recipient"), "");
  const restored = updateHonorField(updated, "issuer", { hidden: false });
  assert.equal(honorFieldValue(restored, "issuer"), existing.subtitle);
  assert.equal(honorFieldHidden(restored, "issuer"), false);
});

test("only reviewed honors can be added and missing section is created", /* 待核对、失败和已取消资料不能误入成品 */ () => {
  const original = newDocument();
  original.sections = original.sections.filter(
    /* 模拟用户已移除默认荣誉栏目 */ (section) => section.id !== "honors",
  );
  const item = honor();
  assert.equal(addHonors(original, [{ ...item, status: "review" }]), original);
  assert.equal(addHonors(original, [{ ...item, reviewed: false }]), original);
  const composed = addHonors(original, [item]);
  assert.equal(composed.sections.at(-1).title, "荣誉证书");
  assert.equal(composed.sections.at(-1).parent_id, null);
  assert.throws(
    /* 过期目标不能偷偷创建新栏目 */ () =>
      addHonors(original, [item], "deleted"),
    /不存在/,
  );
});

test("honors respect explicit targets, entry limits and search fields", /* 自定义栏目、容量边界和编号检索均维持可预期结果 */ () => {
  const original = newDocument();
  const item = honor();
  const composed = addHonors(original, [item], "skills");
  assert.equal(
    composed.sections.find(
      /* 选择用户明确指定的栏目 */ (section) => section.id === "skills",
    ).entries.length,
    1,
  );
  assert.equal(matchesHonor(item, "demo-001"), true);
  assert.equal(matchesHonor(item, "组委会"), true);
  assert.equal(matchesHonor(item, "无关词"), false);
  const section = original.sections.find(
    /* 构造已满栏目以验证容量错误 */ (section) => section.id === "honors",
  );
  section.entries = Array.from(
    { length: 100 },
    /* 每条有独立标识 */ (_, index) => ({ id: `old-${index}` }),
  );
  assert.throws(
    /* 加入荣誉前校验简历容量 */ () => addHonors(original, [item]),
    /100/,
  );
});
