import test from "node:test";
import assert from "node:assert/strict";
import { newDocument, newEntry } from "../src/shared/resume/document.ts";
import {
  pageLayout,
  resetPageLayout,
  withPageLayout,
  LAYOUT_KEY,
} from "../src/shared/resume/pageLayout.ts";
import {
  itemKey,
  layoutItems,
  effectiveItemStyle,
  declaredItemStyle,
  itemLinked,
  setItemLinked,
  updateItemStyle,
  itemCss,
  validItemStyleNumber,
  paragraphCss,
} from "../src/shared/resume/itemLayout.ts";

test("字号只接受 Word 支持的半磅步长，段距及行距保留有效精度", () => {
  assert.equal(validItemStyleNumber("font_size", 10.5), true);
  assert.equal(validItemStyleNumber("font_size", 10.25), false);
  assert.equal(validItemStyleNumber("font_size", 5.5), false);
  assert.equal(validItemStyleNumber("font_size", 72.5), false);
  assert.equal(validItemStyleNumber("space_after", 1.25), true);
  assert.equal(validItemStyleNumber("line_spacing", 1.05), true);
  assert.equal(validItemStyleNumber("space_before", -1), false);
  assert.equal(validItemStyleNumber("line_spacing", Number.NaN), false);
});

test("共行显式段距取最大值，未设置项的全局继承不抢占显式覆盖", () => {
  const phone = { key: itemKey("personal", "phone"), type: "personal" };
  const email = { key: itemKey("personal", "email"), type: "personal" };
  const options = {
    target_pages: 1,
    space_after: 6,
    line_spacing: 1.5,
    item_styles: {
      types: {},
      items: {
        [phone.key]: { space_before: 2, space_after: 1, line_spacing: 1.1 },
      },
    },
  };
  assert.deepEqual(paragraphCss(options, [phone, email]), {
    marginTop: "2pt",
    marginBottom: "1pt",
    lineHeight: 1.1,
  });
  options.item_styles.items[email.key] = {
    space_before: 5,
    space_after: 3,
    line_spacing: 1.3,
  };
  assert.deepEqual(paragraphCss(options, [phone, email]), {
    marginTop: "5pt",
    marginBottom: "3pt",
    lineHeight: 1.3,
  });
});

const first = {
  key: itemKey("project", "p1", "description"),
  type: "body",
  label: "相同文字",
};
const second = {
  key: itemKey("project", "p2", "description"),
  type: "body",
  label: "相同文字",
};

test("同类默认联动，解链复制当前显式值，复链重新使用类型样式", () => {
  const original = { target_pages: 1, font_size: 11, space_after: 5 };
  let options = updateItemStyle(original, first, "font_size", 10);
  options = updateItemStyle(options, first, "space_before", 3);
  assert.equal(effectiveItemStyle(options, second).font_size, 10);
  options = setItemLinked(options, first, false);
  assert.equal(itemLinked(options, first), false);
  assert.deepEqual(options.item_styles.items[first.key], {
    font_size: 10,
    space_before: 3,
  });
  options = updateItemStyle(options, second, "font_size", 12);
  assert.equal(effectiveItemStyle(options, first).font_size, 10);
  assert.equal(effectiveItemStyle(options, second).font_size, 12);
  options = updateItemStyle(options, first, "space_before", 4);
  assert.equal(effectiveItemStyle(options, second).space_before, 3);
  options = setItemLinked(options, first, true);
  assert.equal(itemLinked(options, first), true);
  assert.equal(effectiveItemStyle(options, first).font_size, 12);
  assert.equal(effectiveItemStyle(options, first).space_before, 3);
  assert.deepEqual(original, {
    target_pages: 1,
    font_size: 11,
    space_after: 5,
  });
});

test("标题解链只固定类型声明，全局段距不被错误固化到模板标题", () => {
  const heading = {
    key: itemKey("section", "education", "title"),
    type: "section_title",
    label: "教育",
  };
  const options = {
    target_pages: 1,
    font_size: 10,
    space_after: 1,
    line_spacing: 1.05,
    item_styles: { types: { section_title: { font_size: 16 } }, items: {} },
  };
  const unlinked = setItemLinked(options, heading, false);
  assert.deepEqual(unlinked.item_styles.items[heading.key], { font_size: 16 });
  assert.deepEqual(declaredItemStyle(unlinked, heading), { font_size: 16 });
  assert.deepEqual(
    declaredItemStyle(
      setItemLinked({ target_pages: 1, space_after: 1 }, heading, false),
      heading,
    ),
    {},
  );
});

test("独立空对象阻断类型继承，清空单项值恢复全局或模板", () => {
  let options = {
    target_pages: 1,
    font_size: 11,
    item_styles: {
      types: { body: { font_size: 10, space_before: 6 } },
      items: { [first.key]: {} },
    },
  };
  assert.equal(itemLinked(options, first), false);
  assert.deepEqual(effectiveItemStyle(options, first), { font_size: 11 });
  options = updateItemStyle(options, first, "font_size", 14);
  options = updateItemStyle(options, first, "font_size", undefined);
  assert.equal(effectiveItemStyle(options, first).font_size, 11);
  assert.equal(itemLinked(options, first), false);
});

test("重名、分隔符及中文标识不会混淆，改名排序不改变样式归属", () => {
  const document = newDocument();
  document.personal.name = "合成姓名";
  document.personal.custom_fields = [
    { id: "a:b", label: "信息", value: "相同文字", visible: true },
  ];
  const entry = {
    ...newEntry(),
    id: "甲:乙",
    title: "相同文字",
    details: "相同文字",
  };
  const education = document.sections.find(
    (section) => section.id === "education",
  );
  education.entries = [entry, { ...entry, id: "甲", custom_fields: [] }];
  const initial = layoutItems(document, []);
  entry.title = "改名";
  education.entries.reverse();
  const changed = layoutItems(document, []);
  assert.deepEqual(
    initial.map((item) => item.key).sort(),
    changed.map((item) => item.key).sort(),
  );
  assert.notEqual(
    itemKey("entry", "a:b", "c", "details"),
    itemKey("entry", "a", "b:c", "details"),
  );
  assert.equal(
    itemKey("entry", "教育", "甲:乙", "details"),
    '["entry","教育","甲:乙","details"]',
  );
});

test("可见项遵守栏目、父栏目、字段定义、项目覆盖及固定亮点", () => {
  const document = newDocument();
  document.personal.name = "不展示";
  document.personal.hidden_fields = ["name"];
  document.personal.custom_fields = [
    { id: "empty", label: "", value: "内容", visible: true },
  ];
  document.sections.find((section) => section.id === "education").visible =
    false;
  document.project_visibility = {
    p1: { fields: { role: false }, custom_fields: { c1: true } },
  };
  const content = {
    title: "项目",
    period: "2026",
    role: "角色",
    stack: ["Python"],
    description: "正文",
    custom_fields: [
      {
        id: "c1",
        label: "网址",
        value: "https://example.test",
        visible: false,
      },
    ],
    highlights: [
      { id: "h1", title: "亮点一", text: "正文" },
      { id: "h2", title: "亮点二", text: "正文" },
    ],
  };
  const items = [
    { project_id: "p1", revision_id: "r1", highlight_ids: ["h2"], content },
  ];
  const keys = layoutItems(document, items).map((item) => item.key);
  for (const key of [
    itemKey("personal", "name"),
    itemKey("section", "courses", "title"),
    itemKey("project", "p1", "role"),
    itemKey("project", "p1", "highlight", "h1"),
  ])
    assert.equal(keys.includes(key), false);
  assert.equal(
    keys.includes(itemKey("project", "p1", "highlight", "h2")),
    true,
  );
  assert.equal(keys.includes(itemKey("project", "p1", "custom", "c1")), true);
  assert.deepEqual(
    layoutItems(document, items).map((item) => item.key),
    layoutItems(document, [{ ...items[0], revision_id: "r2" }]).map(
      (item) => item.key,
    ),
  );
});

test("自动压页在有效样式上执行，保留更小字号、紧行距及标题层级", () => {
  const options = {
    target_pages: 1,
    font_size: 10,
    auto_fit: { spacing_factor: 0.5, font_delta: 2 },
    item_styles: {
      types: {
        body: {
          font_size: 8,
          space_before: 4,
          space_after: 6,
          line_spacing: 0.9,
        },
      },
      items: {},
    },
  };
  assert.deepEqual(itemCss(options, first.key, "body"), {
    fontSize: "8pt",
    marginTop: "2pt",
    marginBottom: "3pt",
    lineHeight: 0.9,
  });
  assert.equal(
    itemCss(options, itemKey("personal", "name"), "name").fontSize,
    "16.75pt",
  );
  assert.equal(
    effectiveItemStyle(options, { key: "name", type: "name", label: "" })
      .font_size,
    undefined,
  );
});

test("恢复模板清除逐项及自动设置，同时保留同一命名空间的未知扩展", () => {
  const document = newDocument();
  document.extensions = {
    [LAYOUT_KEY]: {
      extra: { preserved: true },
      display: { hidden: true, future: "value" },
      options: {
        target_pages: 2,
        future: "option",
        item_styles: { types: { body: { font_size: 10 } }, items: {} },
        auto_fit: { spacing_factor: 0, font_delta: 2 },
      },
    },
  };
  const restored = withPageLayout(
    document,
    resetPageLayout(pageLayout(document)),
  );
  assert.deepEqual(pageLayout(restored), { target_pages: 2, future: "option" });
  assert.deepEqual(restored.extensions[LAYOUT_KEY].extra, { preserved: true });
  assert.deepEqual(restored.extensions[LAYOUT_KEY].display, {
    hidden: true,
    future: "value",
  });
  assert.equal(restored.personal, document.personal);
});
