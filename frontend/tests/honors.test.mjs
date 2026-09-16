import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addHonors,
  emptyHonor,
  hasHonor,
  matchesHonor,
} from "../src/features/honors/model.ts";
import { newDocument } from "../src/features/profile/document.ts";

/** 生成不依赖服务端或个人资料的已核对荣誉。 */
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
    },
    attachment: null,
  };
}

test("honors copy to a resume without duplicates or later library changes", /* 验证跨栏目去重、资料快照和其他栏目保留。 */ () => {
  const original = newDocument();
  const item = honor();
  const composed = addHonors(original, [item]);
  const entry = composed.sections.find(
    /* 查找目标栏目。 */ (section) => section.id === "honors",
  ).entries[0];
  assert.equal(entry.title, "示例竞赛 · 一等奖");
  assert.equal(entry.subtitle, "示例组委会");
  assert.equal(entry.period, "2026-06");
  assert.equal(hasHonor(composed, item.id), true);
  assert.equal(hasHonor(original, item.id), false);
  assert.equal(addHonors(composed, [item]), composed);
  item.fields.name = "修改后的名称";
  assert.equal(entry.title, "示例竞赛 · 一等奖");
  assert.equal(
    original.sections.find(
      /* 原始草稿保持不变。 */ (section) => section.id === "honors",
    ).entries.length,
    0,
  );
});

test("only reviewed honors can be added and missing section is created", /* 待核对、失败和已取消资料不能误入成品。 */ () => {
  const original = newDocument();
  original.sections = original.sections.filter(
    /* 模拟用户已移除默认荣誉栏目。 */ (section) => section.id !== "honors",
  );
  const item = honor();
  assert.equal(addHonors(original, [{ ...item, status: "review" }]), original);
  assert.equal(addHonors(original, [{ ...item, reviewed: false }]), original);
  const composed = addHonors(original, [item]);
  assert.equal(composed.sections.at(-1).title, "荣誉证书");
  assert.equal(composed.sections.at(-1).parent_id, null);
  assert.throws(
    /* 过期目标不能偷偷创建新栏目。 */ () =>
      addHonors(original, [item], "deleted"),
    /不存在/,
  );
});

test("honors respect explicit targets, entry limits and search fields", /* 自定义栏目、容量边界和编号检索均维持可预期结果。 */ () => {
  const original = newDocument();
  const item = honor();
  const composed = addHonors(original, [item], "skills");
  assert.equal(
    composed.sections.find(
      /* 选择用户明确指定的栏目。 */ (section) => section.id === "skills",
    ).entries.length,
    1,
  );
  assert.equal(matchesHonor(item, "demo-001"), true);
  assert.equal(matchesHonor(item, "组委会"), true);
  assert.equal(matchesHonor(item, "无关词"), false);
  const section = original.sections.find(
    /* 构造已满栏目以验证容量错误。 */ (section) => section.id === "honors",
  );
  section.entries = Array.from(
    { length: 100 },
    /* 每条有独立标识。 */ (_, index) => ({ id: `old-${index}` }),
  );
  assert.throws(
    /* 加入前检查容量，不产生无法保存的简历。 */ () =>
      addHonors(original, [item]),
    /100/,
  );
});
