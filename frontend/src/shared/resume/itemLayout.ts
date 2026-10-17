import type { CSSProperties } from "react";
import type {
  DefaultField,
  Experience,
  ResumeDocument,
  ResumeItem,
} from "../types/index.ts";
import type { AutoFit, ItemStyle, PageLayout } from "./pageLayout.ts";
import { fieldVisible } from "./visibility.ts";
import { projectBodyOrder } from "./bodyOrder.ts";

export interface LayoutItem {
  key: string;
  type: string;
  label: string;
  searchText?: string;
}
export type LayoutPreviewItem = ResumeItem & { content: Experience };
export const ITEM_TYPE_LABELS: Record<string, string> = {
  name: "姓名",
  job_title: "求职意向",
  personal: "个人信息",
  section_title: "栏目标题",
  title: "条目标题",
  subtitle: "副标题",
  period: "时间",
  body: "正文",
  role: "担任角色",
  stack: "技术栈",
  highlight: "项目亮点",
  custom: "自定义信息",
};
const FIELD_LABELS: Record<string, string> = {
  name: "姓名",
  job_title: "求职意向",
  gender: "性别",
  age: "年龄",
  phone: "电话",
  email: "邮箱",
  gpa: "成绩",
  location: "所在地",
  website: "个人主页",
  title: "标题",
  subtitle: "副标题",
  period: "时间",
  details: "内容",
  role: "担任角色",
  stack: "技术栈",
  description: "项目描述",
};

/** 使用元组编码稳定标识，名称、顺序及经历版本变化不会改变归属 */
export function itemKey(...parts: string[]): string {
  return JSON.stringify(parts);
}

/** 默认字段缺席时沿用旧资料，明确删除及隐藏的字段不进入排版 */
export function layoutFieldVisible(
  key: string,
  hidden: string[],
  definitions?: DefaultField[] | null,
): boolean {
  return (
    !hidden.includes(key) &&
    (!definitions || !!definitions.find((field) => field.id === key)?.visible)
  );
}

/** 让编辑器及内容预览按相同的语义类型归类 */
export function itemType(scope: string, field: string): string {
  if (scope === "personal")
    return field === "name" || field === "job_title" ? field : "personal";
  if (scope === "section") return "section_title";
  return field === "description" || field === "details" ? "body" : field;
}

/** 字号使用 Word 支持的半磅步长，间距保留输入精度 */
export function validItemStyleNumber(
  field: keyof ItemStyle,
  value: number,
): boolean {
  const limits = {
    font_size: [6, 72],
    space_before: [0, 48],
    space_after: [0, 48],
    line_spacing: [0.8, 3],
  };
  const [min, max] = limits[field];
  return (
    Number.isFinite(value) &&
    value >= min &&
    value <= max &&
    (field !== "font_size" || Number.isInteger(value * 2))
  );
}

/** 只列出会进入简历的文字项，并保留每个亮点及自定义项的身份 */
export function layoutItems(
  document: ResumeDocument,
  items: LayoutPreviewItem[],
): LayoutItem[] {
  const result: LayoutItem[] = [];
  /** 省略空文字，标签只用于选择，不参与样式寻址 */
  function add(parts: string[], type: string, label: string, text: string) {
    if (text.trim())
      result.push({
        key: itemKey(...parts),
        type,
        label: `${label} · ${text.slice(0, 36)}`,
        searchText: text,
      });
  }
  const personal = document.personal;
  for (const field of [
    "name",
    "job_title",
    "gender",
    "age",
    "phone",
    "email",
    "gpa",
    "location",
    "website",
  ] as const)
    if (
      layoutFieldVisible(
        field,
        personal.hidden_fields,
        personal.field_definitions,
      )
    )
      add(
        ["personal", field],
        itemType("personal", field),
        FIELD_LABELS[field],
        personal[field],
      );
  for (const field of personal.custom_fields)
    if (field.visible && field.label.trim())
      add(["personal", "custom", field.id], "custom", field.label, field.value);
  for (const section of document.sections) {
    if (
      !section.visible ||
      (section.parent_id &&
        !document.sections.find((parent) => parent.id === section.parent_id)
          ?.visible)
    )
      continue;
    add(
      ["section", section.id, "title"],
      "section_title",
      "栏目标题",
      section.title,
    );
    if (section.kind === "projects") {
      for (const item of items) {
        const content = item.content;
        const visibility = document.project_visibility?.[item.project_id] ?? {};
        for (const field of [
          "title",
          "period",
          ...projectBodyOrder(content, visibility),
        ]) {
          if (field === "highlights") {
            for (const point of content.highlights)
              if (item.highlight_ids.includes(point.id))
                add(
                  ["project", item.project_id, "highlight", point.id],
                  "highlight",
                  `${content.title} / 亮点`,
                  `${point.title} ${point.text}`,
                );
          } else if (field.startsWith("custom:")) {
            const custom = content.custom_fields?.find(
              (value) => `custom:${value.id}` === field,
            );
            if (
              custom &&
              custom.label.trim() &&
              (visibility.custom_fields?.[custom.id] ?? custom.visible)
            )
              add(
                ["project", item.project_id, "custom", custom.id],
                "custom",
                `${content.title} / ${custom.label}`,
                custom.value,
              );
          } else if (
            field === "title" ||
            field === "period" ||
            field === "role" ||
            field === "stack" ||
            field === "description"
          ) {
            if (
              fieldVisible(content, visibility, field) &&
              layoutFieldVisible(field, [], section.field_definitions)
            )
              add(
                ["project", item.project_id, field],
                itemType("project", field),
                `${content.title} / ${FIELD_LABELS[field]}`,
                field === "stack" ? content.stack.join(" · ") : content[field],
              );
          }
        }
      }
    } else
      for (const entry of section.entries) {
        if (!entry.visible) continue;
        for (const field of ["title", "subtitle", "period", "details"] as const)
          if (
            layoutFieldVisible(
              field,
              entry.hidden_fields,
              entry.field_definitions ?? section.field_definitions,
            )
          )
            add(
              ["entry", section.id, entry.id, field],
              itemType("entry", field),
              `${section.title} / ${entry.title || "条目"} / ${FIELD_LABELS[field]}`,
              entry[field],
            );
        for (const field of entry.custom_fields)
          if (field.visible && field.label.trim())
            add(
              ["entry", section.id, entry.id, "custom", field.id],
              "custom",
              `${section.title} / ${field.label}`,
              field.value,
            );
      }
  }
  return [...new Map(result.map((item) => [item.key, item])).values()];
}

/** 空对象同样表示解链，独立项不会混入后续同类修改 */
export function itemLinked(layout: PageLayout, item: LayoutItem): boolean {
  return !Object.hasOwn(layout.item_styles?.items ?? {}, item.key);
}

/** 控件只显示类型或单项明确设置，模板及全局的实际继承不猜测为数值 */
export function declaredItemStyle(
  layout: PageLayout,
  item: LayoutItem,
): ItemStyle {
  const override = itemLinked(layout, item)
    ? layout.item_styles?.types?.[item.type]
    : layout.item_styles?.items?.[item.key];
  const result: ItemStyle = {};
  for (const field of [
    "font_size",
    "space_before",
    "space_after",
    "line_spacing",
  ] as const)
    if (typeof override?.[field] === "number") result[field] = override[field];
  return result;
}

/** 内容预览按概略全局样式显示，解链项完整替代类型覆盖 */
export function effectiveItemStyle(
  layout: PageLayout,
  item: LayoutItem,
): ItemStyle {
  const global: ItemStyle = {};
  for (const field of ["font_size", "space_after", "line_spacing"] as const)
    if (
      typeof layout[field] === "number" &&
      (field !== "font_size" ||
        !["name", "job_title", "section_title"].includes(item.type))
    )
      global[field] = layout[field];
  return { ...global, ...declaredItemStyle(layout, item) };
}

/** 解链复制类型声明并继续继承全局或模板，复链移除独立覆盖 */
export function setItemLinked(
  layout: PageLayout,
  item: LayoutItem,
  linked: boolean,
): PageLayout {
  const styles = {
    ...layout.item_styles,
    types: { ...layout.item_styles?.types },
    items: { ...layout.item_styles?.items },
  };
  if (linked) delete styles.items[item.key];
  else styles.items[item.key] = declaredItemStyle(layout, item);
  return { ...layout, item_styles: styles };
}

/** 联动修改类型，独立修改单项；清空某个数值会恢复该参数的继承 */
export function updateItemStyle(
  layout: PageLayout,
  item: LayoutItem,
  field: keyof ItemStyle,
  value: number | undefined,
): PageLayout {
  const linked = itemLinked(layout, item);
  const styles = {
    ...layout.item_styles,
    types: { ...layout.item_styles?.types },
    items: { ...layout.item_styles?.items },
  };
  const bucket = linked ? styles.types : styles.items;
  const key = linked ? item.type : item.key;
  const next = { ...bucket[key] };
  if (value === undefined) delete next[field];
  else next[field] = value;
  bucket[key] = next;
  return { ...layout, item_styles: styles };
}

/** 兼容旧减字结果，新比例向下量化到半磅，原本更小的文字不会被放大 */
export function autoFitFontSize(size: number, fit: AutoFit): number {
  const legacy = Math.min(size, Math.max(9, size - (fit.font_delta ?? 0)));
  const scale = fit.font_scale ?? 1;
  if (scale === 1 || legacy < 6) return legacy;
  return Math.floor(Math.min(legacy, Math.max(6, legacy * scale)) * 2) / 2;
}

/** 内容预览按自身字号层级应用通用压缩，实际分页继续由 Word 测量 */
export function itemCss(
  layout: PageLayout,
  key: string,
  type: string,
): CSSProperties {
  const style = effectiveItemStyle(layout, { key, type, label: "" });
  if (layout.auto_fit) {
    const factor = layout.auto_fit.spacing_factor ?? 1;
    const scope = (JSON.parse(key) as string[])[0];
    const heading =
      type === "name" ||
      type === "section_title" ||
      (type === "title" && scope === "project");
    const contact =
      scope === "personal" && type !== "custom" && type !== "name";
    // 内容预览使用自身现有 CSS 的基准，自动压缩不放大模板未指定的文字或空白
    const size =
      style.font_size ??
      (type === "name"
        ? 18.75
        : type === "section_title"
          ? 12.75
          : heading
            ? 11.25
            : 9.75);
    style.font_size = autoFitFontSize(size, layout.auto_fit);
    style.space_before =
      (style.space_before ??
        (type === "name" ? 7.5 : type === "section_title" ? 16.5 : 0)) * factor;
    style.space_after =
      (style.space_after ??
        (type === "name" || (!heading && !contact && type !== "highlight")
          ? 7.5
          : 0)) * factor;
    const line =
      style.line_spacing ??
      (type === "name" ? 1.45 : heading || contact ? 1.2 : 1.6);
    style.line_spacing = Math.min(line, 1 + (line - 1) * factor);
  }
  return {
    fontSize:
      style.font_size === undefined ? undefined : `${style.font_size}pt`,
    marginTop:
      style.space_before === undefined ? undefined : `${style.space_before}pt`,
    marginBottom:
      style.space_after === undefined ? undefined : `${style.space_after}pt`,
    lineHeight: style.line_spacing,
  };
}

/** 共行文字共享段落属性，只在明确声明中取最大值，未声明时继续继承全局 */
export function paragraphCss(
  layout: PageLayout,
  items: Pick<LayoutItem, "key" | "type">[],
): CSSProperties {
  const explicit = items.map((item) =>
    declaredItemStyle(layout, { ...item, label: "" }),
  );
  const style: ItemStyle = {};
  for (const field of [
    "space_before",
    "space_after",
    "line_spacing",
  ] as const) {
    const values = explicit
      .map((item) => item[field])
      .filter((value): value is number => typeof value === "number");
    if (values.length) style[field] = Math.max(...values);
    else if (field !== "space_before" && typeof layout[field] === "number")
      style[field] = layout[field];
  }
  if (layout.auto_fit) {
    const factor = layout.auto_fit.spacing_factor ?? 1;
    style.space_before = (style.space_before ?? 0) * factor;
    style.space_after = (style.space_after ?? 0) * factor;
    const line = style.line_spacing ?? 1.2;
    style.line_spacing = Math.min(line, 1 + (line - 1) * factor);
  }
  return {
    marginTop:
      style.space_before === undefined ? undefined : `${style.space_before}pt`,
    marginBottom:
      style.space_after === undefined ? undefined : `${style.space_after}pt`,
    lineHeight: style.line_spacing,
  };
}
