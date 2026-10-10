import assert from "node:assert/strict";
import { test } from "node:test";
import { addSource } from "../../src/resume_maker/plugin_packages/sys_resume/client/features/profile/sourceState.ts";
import { sameSectionEntry } from "../src/shared/resume/comparison.ts";

test("选择通用资料产生独立草稿并阻止重复来源，来源版本影响新旧比较", () => {
  const section = { id: "notes", kind: "text", entries: [] };
  const item = {
    id: "synthetic",
    version: "1",
    title: "合成资料",
    subtitle: "",
    period: "",
    details: "",
    custom_fields: [],
  };
  const next = addSource(section, "community.example/items", item, "entry");
  assert.equal(section.entries.length, 0);
  assert.equal(next.entries[0].source.version, "1");
  assert.equal("version" in next.entries[0], false);
  item.title = "后续变更";
  assert.equal(next.entries[0].title, "合成资料");
  assert.throws(
    () => addSource(next, "community.example/items", item, "second"),
    /已加入/,
  );
  const changed = structuredClone(next.entries[0]);
  changed.source.version = "2";
  assert.equal(sameSectionEntry(changed, next.entries[0]), false);
  assert.throws(
    () =>
      addSource(
        { ...section, kind: "projects" },
        "community.example/items",
        item,
        "entry",
      ),
    /固定经历/,
  );
});
