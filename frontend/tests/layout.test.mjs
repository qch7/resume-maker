import { test } from "node:test";
import assert from "node:assert/strict";
import {
  clamp,
  columnSizes,
  DEFAULT_LAYOUT,
  restoreLayout,
} from "../src/layoutState.ts";

test("layout restoration rejects corrupt sizes and preserves valid preferences", () => {
  assert.deepEqual(restoreLayout(null), DEFAULT_LAYOUT);
  const layout = restoreLayout({
    sidebar: "wide",
    composer: NaN,
    settings: 120,
    guideCollapsed: true,
  });
  assert.equal(layout.sidebar, DEFAULT_LAYOUT.sidebar);
  assert.equal(layout.composer, DEFAULT_LAYOUT.composer);
  assert.equal(layout.settings, 120);
  assert.equal(layout.guideCollapsed, true);
});

test("oversized saved columns fit a smaller desktop without hiding the editor", () => {
  const layout = { ...DEFAULT_LAYOUT, sidebar: 520, composer: 1600 };
  for (const width of [981, 1100, 1280, 1600]) {
    const sizes = columnSizes(width, true, layout);
    assert.ok(sizes.sidebar >= 160);
    assert.ok(sizes.composer >= 300);
    assert.ok(width - sizes.sidebar - sizes.composer - 16 >= 320);
  }
  assert.equal(layout.composer, 1600);
});

test("collapsed sidebar releases its width and narrow screens retain a usable workspace", () => {
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

test("drag boundaries keep settings and preview visible", () => {
  assert.equal(clamp(1000, 80, 420), 420);
  assert.equal(clamp(-500, 80, 420), 80);
  assert.equal(clamp(254, 80, 420), 254);
});
