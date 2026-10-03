export interface Domain {
  id: string;
  name: string;
}
export interface RecruitmentPreferences {
  import_policy: "keep" | "update";
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

/** 在当前可见列表中交换相邻收藏，其他领域和过滤条目保持位置 */
export function moveBookmark(
  items: Bookmark[],
  visible: Bookmark[],
  id: string,
  direction: number,
) {
  const index = visible.findIndex((item) => item.id === id);
  const neighbor = visible[index + direction];
  if (!neighbor) return items;
  const next = [...items];
  const from = next.findIndex((item) => item.id === id);
  const to = next.findIndex((item) => item.id === neighbor.id);
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}
