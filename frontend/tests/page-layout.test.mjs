import test from "node:test";
import assert from "node:assert/strict";
import {
  pageLayout,
  withPageLayout,
  resetPageLayout,
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
    future_option: true,
  });
  assert.deepEqual(original, before);
  assert.deepEqual(pageLayout(original), { target_pages: 1 });
  assert.deepEqual(pageLayout(changed), {
    target_pages: 2,
    font_size: 9.5,
    future_option: true,
  });
  assert.deepEqual(
    changed.extensions["example.widget"],
    original.extensions["example.widget"],
  );
  assert.equal(changed.personal, original.personal);
  assert.equal(changed.extensions[LAYOUT_KEY].display.hidden, true);
});

test("旧荣誉专用选项读取时失效，编辑保存保留通用排版、内容及未知扩展", () => {
  const original = newDocument();
  original.personal.name = "合成姓名";
  original.extensions = {
    [LAYOUT_KEY]: {
      display: { hidden: true, future_display: "保留" },
      future_extension: { enabled: true },
      options: {
        target_pages: 2,
        honors_inline: true,
        font_size: 10.5,
        auto_fit: { spacing_factor: 0.5, font_delta: 0 },
        item_styles: { types: { title: { font_size: 12 } }, items: {} },
        future_option: { enabled: true },
      },
    },
    "example.widget": { data: "保留其他插件资料" },
  };
  const before = structuredClone(original);
  const options = pageLayout(original);
  assert.equal(Object.hasOwn(options, "honors_inline"), false);
  assert.equal(options.target_pages, 2);
  assert.deepEqual(options.auto_fit, { spacing_factor: 0.5, font_delta: 0 });
  assert.deepEqual(options.item_styles, {
    types: { title: { font_size: 12 } },
    items: {},
  });
  const saved = withPageLayout(original, { ...options, space_after: 2 });
  assert.equal(
    Object.hasOwn(saved.extensions[LAYOUT_KEY].options, "honors_inline"),
    false,
  );
  assert.equal(pageLayout(saved).space_after, 2);
  assert.deepEqual(pageLayout(saved).future_option, { enabled: true });
  assert.deepEqual(saved.extensions[LAYOUT_KEY].future_extension, {
    enabled: true,
  });
  assert.deepEqual(
    saved.extensions[LAYOUT_KEY].display,
    before.extensions[LAYOUT_KEY].display,
  );
  assert.deepEqual(
    saved.extensions["example.widget"],
    before.extensions["example.widget"],
  );
  assert.equal(saved.personal, original.personal);
  assert.equal(saved.sections, original.sections);
  assert.deepEqual(original, before);
});

test("直接写入或恢复旧版面时清除废弃键，不删除未知参数或修改输入", () => {
  const document = newDocument();
  const legacy = {
    target_pages: 3,
    honors_inline: true,
    font_size: 10,
    future_option: "保留",
  };
  const saved = withPageLayout(document, legacy);
  assert.deepEqual(saved.extensions[LAYOUT_KEY].options, {
    target_pages: 3,
    font_size: 10,
    future_option: "保留",
  });
  assert.deepEqual(resetPageLayout(legacy), {
    target_pages: 3,
    future_option: "保留",
  });
  assert.equal(legacy.honors_inline, true);
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
