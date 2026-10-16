import test from "node:test";
import assert from "node:assert/strict";
import {
  pageLayout,
  withPageLayout,
  LAYOUT_KEY,
} from "../src/shared/resume/pageLayout.ts";
import { newDocument } from "../src/shared/resume/document.ts";

test("版面设置只更新当前方案，旧方案、其他扩展及经历资料保持原样", () => {
  const original = newDocument();
  original.personal.name = "合成姓名";
  original.extensions = {
    "example.widget": { display: { hidden: true }, untouched: true },
  };
  const before = structuredClone(original);
  const changed = withPageLayout(original, {
    target_pages: 2,
    font_size: 9.5,
    honors_inline: true,
  });
  assert.deepEqual(original, before);
  assert.deepEqual(pageLayout(original), { target_pages: 1 });
  assert.deepEqual(pageLayout(changed), {
    target_pages: 2,
    font_size: 9.5,
    honors_inline: true,
  });
  assert.deepEqual(
    changed.extensions["example.widget"],
    original.extensions["example.widget"],
  );
  assert.equal(changed.personal, original.personal);
  assert.equal(changed.extensions[LAYOUT_KEY].display.hidden, true);
});

test("恢复模板只清除格式参数，保留目标页数及原文", () => {
  const document = newDocument();
  const compact = withPageLayout(document, {
    target_pages: 2,
    font_size: 9.5,
    line_spacing: 1.05,
  });
  const restored = withPageLayout(compact, {
    target_pages: pageLayout(compact).target_pages,
  });
  assert.deepEqual(pageLayout(restored), { target_pages: 2 });
  assert.deepEqual(restored.sections, document.sections);
});
