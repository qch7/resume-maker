import { test } from "node:test";
import assert from "node:assert/strict";
import {
  clamp,
  columnSizes,
  DEFAULT_LAYOUT,
  restoreLayout,
  templateSizes,
} from "../src/shared/lib/layout.ts";

test("layout restoration rejects corrupt sizes and preserves valid preferences", /* 验证损坏的布局值被忽略，有效偏好得到保留。 */ () => {
  assert.deepEqual(restoreLayout(null), DEFAULT_LAYOUT);
  const layout = restoreLayout({
    sidebar: "wide",
    composer: NaN,
    settings: 120,
    chatInput: 300,
    guideCollapsed: true,
  });
  assert.equal(layout.sidebar, DEFAULT_LAYOUT.sidebar);
  assert.equal(layout.composer, DEFAULT_LAYOUT.composer);
  assert.equal(layout.settings, 120);
  assert.equal(layout.chatInput, 300);
  assert.equal(
    restoreLayout({ chatInput: NaN }).chatInput,
    DEFAULT_LAYOUT.chatInput,
  );
  assert.equal(layout.guideCollapsed, true);
});

test("oversized saved columns fit a smaller desktop without hiding the editor", /* 验证大尺寸偏好在小视口中仍给编辑器保留空间。 */ () => {
  const layout = { ...DEFAULT_LAYOUT, sidebar: 520, composer: 1600 };
  for (const width of [981, 1100, 1280, 1600]) {
    const sizes = columnSizes(width, true, layout);
    assert.ok(sizes.sidebar >= 160);
    assert.ok(sizes.composer >= 300);
    assert.ok(width - sizes.sidebar - sizes.composer - 16 >= 320);
  }
  assert.equal(layout.composer, 1600);
});

test("collapsed sidebar releases its width and narrow screens retain a usable workspace", /* 验证侧栏收起或窄屏时释放宽度，工作区仍可使用。 */ () => {
  const hidden = columnSizes(1100, false, {
    ...DEFAULT_LAYOUT,
    composer: 2000,
  });
  assert.equal(hidden.sidebar, 0);
  assert.equal(hidden.composer, 772);
  const narrow = columnSizes(760, true, { ...DEFAULT_LAYOUT, sidebar: 500 });
  assert.equal(narrow.sidebar, 432);
  assert.equal(columnSizes(390, true, DEFAULT_LAYOUT).sidebar, 0);
});

test("drag boundaries keep settings and preview visible", /* 验证分隔条边界保留设置区和预览区。 */ () => {
  assert.equal(clamp(1000, 80, 420), 420);
  assert.equal(clamp(-500, 80, 420), 80);
  assert.equal(clamp(254, 80, 420), 254);
});

test("template layout preferences survive storage and fit a smaller window", /* 保留拖动偏好，缩窗时给预览留出空间，重新放大后恢复用户尺寸。 */ () => {
  const stored = {
    ...DEFAULT_LAYOUT,
    templateInspector: 900,
    templateProgress: 380,
    templatePreview: 720,
    templateAssistant: 200,
  };
  const layout = restoreLayout(JSON.parse(JSON.stringify(stored)));
  assert.deepEqual(layout, stored);
  for (const width of [761, 980, 1280, 1600]) {
    const sizes = templateSizes(width, 650, layout);
    assert.ok(width - sizes.inspector - 8 >= 360);
    assert.ok(sizes.progress <= 290);
    assert.equal(sizes.preview, 720);
    assert.equal(sizes.assistant, 200);
  }
  assert.equal(templateSizes(1600, 1000, layout).inspector, 900);
  assert.equal(templateSizes(1600, 1000, layout).progress, 380);
  assert.deepEqual(layout, stored);
  assert.equal(
    restoreLayout({ templateInspector: "wide", templateProgress: NaN })
      .templateInspector,
    DEFAULT_LAYOUT.templateInspector,
  );
});
