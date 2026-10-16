import type { ResumeDocument } from "../types/index.ts";

export const LAYOUT_KEY = "sys.resume.layout";
export interface PageLayout {
  target_pages: number;
  font_size?: number;
  space_after?: number;
  line_spacing?: number;
  honors_inline?: boolean;
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
  return {
    ...document,
    extensions: {
      ...document.extensions,
      [LAYOUT_KEY]: { display: { hidden: true }, options },
    },
  };
}
