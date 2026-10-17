import type { ResumeDocument } from "@resume-maker/plugin-sdk/shared/types/index";
import {
  ITEM_TYPE_LABELS,
  type LayoutItem,
} from "@resume-maker/plugin-sdk/shared/resume/itemLayout";

export interface LayoutItemGroup {
  id: string;
  title: string;
  items: LayoutItem[];
}

/** 按稳定栏目身份分组，搜索同时匹配栏目、字段类型及可见内容 */
export function groupLayoutItems(
  document: ResumeDocument,
  items: LayoutItem[],
  query = "",
): LayoutItemGroup[] {
  const groups = new Map<string, LayoutItemGroup>();
  const search = query.trim().normalize("NFKC").toLocaleLowerCase();
  for (const item of items) {
    const parts = JSON.parse(item.key) as string[];
    const sectionId =
      parts[0] === "project"
        ? document.sections.find((section) => section.kind === "projects")?.id
        : parts[0] === "personal"
          ? undefined
          : parts[1];
    const id =
      parts[0] === "personal" ? "personal" : `section:${sectionId ?? "other"}`;
    const title =
      parts[0] === "personal"
        ? "个人信息"
        : document.sections.find((section) => section.id === sectionId)
            ?.title || "其他文字";
    if (
      search &&
      !`${title} ${ITEM_TYPE_LABELS[item.type] ?? ""} ${item.label} ${item.searchText ?? ""}`
        .normalize("NFKC")
        .toLocaleLowerCase()
        .includes(search)
    )
      continue;
    const group = groups.get(id) ?? { id, title, items: [] };
    group.items.push(item);
    groups.set(id, group);
  }
  return [...groups.values()];
}
