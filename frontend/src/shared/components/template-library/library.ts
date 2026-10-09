import type { Template } from "../../types/index.ts";

export interface LibraryState {
  categories: { id: string; name: string }[];
  items: Record<
    string,
    { category_id: string; liked: boolean; deleted_at?: string }
  >;
  templates?: (Template & { usage_count: number })[];
}
export interface LibraryTemplate extends Template {
  category_id: string;
  liked: boolean;
  deleted_at?: string;
  usage_count: number;
}

/** 为内置和导入模板补上持久化组织信息，新模板默认未分类且未收藏 */
export function libraryTemplates(
  templates: Template[],
  state: LibraryState,
): LibraryTemplate[] {
  return [
    { id: "builtin", name: "内置 · 完整简历", created_at: "", usage_count: 0 },
    ...(state.templates ??
      templates.map(
        /* 未加载库详情前不推断引用数 */ (item) => ({
          ...item,
          usage_count: 0,
        }),
      )),
  ].map(
    /* 分类失效的模板显示在未分类中 */ (template) => {
      const meta = state.items[template.id];
      return {
        ...template,
        deleted_at: meta?.deleted_at,
        liked: meta?.liked ?? false,
        category_id: state.categories.some(
          /* 仅保留当前仍存在的分类 */ (category) =>
            category.id === meta?.category_id,
        )
          ? meta!.category_id
          : "",
      };
    },
  );
}

/** 在当前分类内按名称搜索和排序，两种视图共用同一批结果 */
export function filterTemplates(
  templates: LibraryTemplate[],
  folder: string,
  query: string,
  sort: string,
) {
  const needle = query.trim().toLocaleLowerCase();
  return templates
    .filter(
      /* 收藏视图跨分类，其他视图按分类标识筛选 */ (template) =>
        (folder === "trash" ? !!template.deleted_at : !template.deleted_at) &&
        (folder === "all" ||
          folder === "trash" ||
          (folder === "liked"
            ? template.liked
            : template.category_id === folder)) &&
        template.name.toLocaleLowerCase().includes(needle),
    )
    .sort(
      /* 日期一致时保持可预测的名称顺序 */ (a, b) =>
        (sort === "newest" ? b.created_at.localeCompare(a.created_at) : 0) ||
        a.name.localeCompare(b.name, "zh-CN"),
    );
}

/** 按三十天时长和服务端 UTC 时间计算回收站截止日期 */
export function templateExpiry(deletedAt: string) {
  return new Date(
    Date.parse(deletedAt) + 30 * 24 * 60 * 60 * 1000,
  ).toLocaleString("zh-CN");
}

/** 展示保存日期，内置模板没有登记日期 */
export function templateDate(value: string) {
  return value ? new Date(value).toLocaleDateString("zh-CN") : "内置";
}
