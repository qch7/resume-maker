import type { Template } from "../../types/index.ts";

export interface LibraryState {
  categories: { id: string; name: string }[];
  items: Record<string, { category_id: string; liked: boolean }>;
}
export interface LibraryTemplate extends Template {
  category_id: string;
  liked: boolean;
}

/** 为内置与导入模板补上持久化组织信息；新模板默认未分类且未收藏。 */
export function libraryTemplates(
  templates: Template[],
  state: LibraryState,
): LibraryTemplate[] {
  return [
    { id: "builtin", name: "内置 · 完整简历", created_at: "" },
    ...templates,
  ].map(
    /* 所属分类已失效时回到未分类，不影响原模板。 */ (template) => {
      const meta = state.items[template.id];
      return {
        ...template,
        liked: meta?.liked ?? false,
        category_id: state.categories.some(
          /* 仅保留当前仍存在的分类。 */ (category) =>
            category.id === meta?.category_id,
        )
          ? meta!.category_id
          : "",
      };
    },
  );
}

/** 在当前分类内按名称搜索与排序，两种视图共用同一批结果。 */
export function filterTemplates(
  templates: LibraryTemplate[],
  folder: string,
  query: string,
  sort: string,
) {
  const needle = query.trim().toLocaleLowerCase();
  return templates
    .filter(
      /* 收藏视图跨分类，其他视图按分类标识筛选。 */ (template) =>
        (folder === "all" ||
          (folder === "liked"
            ? template.liked
            : template.category_id === folder)) &&
        template.name.toLocaleLowerCase().includes(needle),
    )
    .sort(
      /* 日期一致时保持可预测的名称顺序。 */ (a, b) =>
        (sort === "newest" ? b.created_at.localeCompare(a.created_at) : 0) ||
        a.name.localeCompare(b.name, "zh-CN"),
    );
}

/** 展示保存日期，内置模板没有登记日期。 */
export function templateDate(value: string) {
  return value ? new Date(value).toLocaleDateString("zh-CN") : "内置";
}
