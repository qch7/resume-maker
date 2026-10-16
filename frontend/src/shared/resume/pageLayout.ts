import type { ResumeDocument } from "../types/index.ts";

export const LAYOUT_KEY = "sys.resume.layout";
export interface ItemStyle {
  font_size?: number;
  space_before?: number;
  space_after?: number;
  line_spacing?: number;
}
export interface PageLayout {
  target_pages: number;
  font_size?: number;
  space_after?: number;
  line_spacing?: number;
  honors_inline?: boolean;
  item_styles?: {
    types: Record<string, ItemStyle>;
    items: Record<string, ItemStyle>;
  };
  auto_fit?: { spacing_factor: number; font_delta: number };
  [key: string]: unknown;
}

/** 各方案独立读取版面设置，旧方案继续沿用模板原样 */
export function pageLayout(
  document: ResumeDocument | null | undefined,
): PageLayout {
  const value = document?.extensions?.[LAYOUT_KEY];
  const options =
    value && typeof value === "object" && "options" in value
      ? value.options
      : null;
  return {
    target_pages: 1,
    ...(options && typeof options === "object" ? options : {}),
  };
}

/** 只写当前版面选项，其他插件资料、经历及显隐保持原样 */
export function withPageLayout(
  document: ResumeDocument,
  options: PageLayout,
): ResumeDocument {
  const existing = document.extensions?.[LAYOUT_KEY];
  const extension = existing && typeof existing === "object" ? existing : {};
  const display =
    "display" in extension &&
    extension.display &&
    typeof extension.display === "object"
      ? extension.display
      : {};
  return {
    ...document,
    extensions: {
      ...document.extensions,
      [LAYOUT_KEY]: {
        ...extension,
        display: { ...display, hidden: true },
        options,
      },
    },
  };
}

/** 恢复已知格式参数，页数预算及扩展选项继续保留 */
export function resetPageLayout(value: PageLayout): PageLayout {
  const result = { ...value };
  for (const key of [
    "font_size",
    "space_after",
    "line_spacing",
    "honors_inline",
    "item_styles",
    "auto_fit",
  ])
    delete result[key];
  return result;
}
