export interface Domain {
  id: string;
  name: string;
}
export interface RecruitmentPreferences {
  import_policy: "keep" | "update";
}
export type BookmarkSort = "default" | "asc" | "desc";
export interface DisplayPreferences {
  view: "cards" | "list";
  sort: BookmarkSort;
}

/** 恢复视图和排序偏好，损坏或过期的值回退到卡片及原始顺序 */
export function restoreDisplayPreferences(value: unknown): DisplayPreferences {
  const saved =
    value && typeof value === "object"
      ? (value as Partial<DisplayPreferences>)
      : {};
  return {
    view: saved.view === "list" ? "list" : "cards",
    sort:
      saved.sort === "asc" || saved.sort === "desc" ? saved.sort : "default",
  };
}
export interface Bookmark {
  id: string;
  name: string;
  domain_id: string;
  category: string;
  description: string;
  tags: string[];
  notes: string;
  favorite: boolean;
  links: { label: string; url: string }[];
}
export interface BookmarkFile {
  format: "resume-maker.recruitment-bookmarks";
  schema_version: 1;
  domains: Domain[];
  categories: Domain[];
  bookmarks: Bookmark[];
}
export interface Snapshot {
  revision: number;
  data: BookmarkFile;
}
export interface ImportSummary {
  revision: number;
  added: number;
  updated: number;
  skipped: number;
  domains_added: number;
  categories_added: number;
  changes: { name: string; action: "added" | "updated" | "skipped" }[];
}

/** 创建空白收藏，领域和分类均可不选 */
export function newBookmark(domain: string): Bookmark {
  return {
    id: crypto.randomUUID(),
    name: "",
    domain_id: domain,
    category: "",
    description: "",
    tags: [],
    notes: "",
    favorite: false,
    links: [{ label: "招聘官网", url: "" }],
  };
}

/** 按领域、分类、收藏和关键词筛选，保留用户原有排序 */
export function filterBookmarks(
  items: Bookmark[],
  domain: string,
  category: string,
  favorites: boolean,
  query: string,
) {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return items.filter((item) => {
    const text = [
      item.name,
      item.description,
      item.notes,
      ...item.tags,
      ...item.links.flatMap((link) => [link.label, link.url]),
    ]
      .join(" ")
      .toLocaleLowerCase();
    return (
      (!domain || item.domain_id === domain) &&
      (!category || item.category === category) &&
      (!favorites || item.favorite) &&
      words.every((word) => text.includes(word))
    );
  });
}

/** 全部网站保留完整分类，领域和星标只显示当前范围实际使用的分类 */
export function scopeCategories(
  categories: Domain[],
  items: Bookmark[],
  domain: string,
  favorites: boolean,
) {
  if (!domain && !favorites) return categories;
  const used = new Set(
    items
      .filter(
        (item) =>
          (!domain || item.domain_id === domain) &&
          (!favorites || item.favorite),
      )
      .map((item) => item.category),
  );
  return categories.filter((category) => used.has(category.id));
}

/** 星标优先置顶，组内按文件顺序或名称拼音排序，保持源数组不变 */
export function sortBookmarks(items: Bookmark[], order: BookmarkSort) {
  const names = new Intl.Collator("zh-CN-u-co-pinyin", {
    numeric: true,
    sensitivity: "base",
  });
  return [...items].sort((left, right) => {
    const starred = Number(right.favorite) - Number(left.favorite);
    if (starred || order === "default") return starred;
    const compared = names.compare(left.name, right.name);
    return order === "desc" ? -compared : compared;
  });
}
