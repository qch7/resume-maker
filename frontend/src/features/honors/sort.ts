import type { HonorSource } from "../../shared/types/honors.ts";
import type { ResumeSection } from "../../shared/types/index.ts";
import { isHonorEntry } from "./entry.ts";
import type { Honor } from "./model.ts";

export type HonorSortKey = "recent" | "date" | "name";
export interface HonorSort {
  key: HonorSortKey;
  direction: "asc" | "desc";
}
export const DEFAULT_HONOR_SORT: HonorSort = {
  key: "recent",
  direction: "desc",
};
const names = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});

/** 再次点击当前维度时反转；切换维度时日期默认从新到旧、名称默认正序 */
export function nextHonorSort(
  current: HonorSort | null,
  key: HonorSortKey,
): HonorSort {
  return {
    key,
    direction:
      current?.key === key
        ? current.direction === "asc"
          ? "desc"
          : "asc"
        : key === "name"
          ? "asc"
          : "desc",
  };
}

/** 将年月日、中文日期及斜杠日期按日历解析；空白与无效值保持未知 */
function awardDate(value: string): number | null {
  const parts = value
    .replace(/\s/g, "")
    .match(/^(\d{4})(?:[-/.年](\d{1,2})(?:[-/.月](\d{1,2}))?)?[月日]?$/);
  if (!parts) return null;
  const year = Number(parts[1]),
    month = Number(parts[2] ?? 1),
    day = Number(parts[3] ?? 1);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
    ? date.getTime()
    : null;
}

interface SortValues {
  name: string;
  date: string;
  updatedAt?: string;
}

/** 比较实际日期和自然名称；缺失值始终置后；同值条目保留原有顺序 */
function sortItems<T>(
  items: T[],
  sort: HonorSort,
  values: (item: T) => SortValues,
): T[] {
  /** 每项只解析一次排序键以免比较过程中重复处理日期 */
  function key(item: T) {
    const fields = values(item);
    if (sort.key === "name") return fields.name.trim() || null;
    if (sort.key === "date") return awardDate(fields.date);
    const stamp = Date.parse(fields.updatedAt ?? "");
    return Number.isFinite(stamp) ? stamp : null;
  }
  return items
    .map(
      /* 将排序键和原条目绑定且不修改资料内容 */ (item) => ({
        item,
        key: key(item),
      }),
    )
    .sort(
      /* 正倒序只影响有效值；未知值以及同值的相对顺序保持稳定 */ (a, b) => {
        if (a.key === null || b.key === null)
          return a.key === b.key ? 0 : a.key === null ? 1 : -1;
        const order =
          typeof a.key === "number" && typeof b.key === "number"
            ? a.key - b.key
            : names.compare(String(a.key), String(b.key));
        return sort.direction === "asc" ? order : -order;
      },
    )
    .map(/* 排序只重排引用；完整资料和勾选身份保持不变 */ ({ item }) => item);
}

/** 荣誉库筛选后的卡片使用与栏目编排一致的比较规则 */
export function sortHonors(items: Honor[], sort: HonorSort): Honor[] {
  return sortItems(
    items,
    sort,
    /* 从库记录读取三种排序字段 */ (item) => ({
      name: item.fields.name,
      date: item.fields.date,
      updatedAt: item.updated_at,
    }),
  );
}

/** 只重排本栏目的荣誉位置；混合栏目的其他资料、显隐及来源引用原样保留 */
export function sortHonorEntries(
  section: ResumeSection,
  honors: HonorSource[],
  sort: HonorSort,
) {
  const sources = new Map(
    honors.map(
      /* 用来源标识关联更新时间以免同名荣誉串联 */ (honor) => [
        `honor:${honor.id}`,
        honor,
      ],
    ),
  );
  const entries = sortItems(
    section.entries.filter(
      /* 自定义栏目只排序其中的荣誉 */ (entry) => isHonorEntry(entry, section),
    ),
    sort,
    /* 日期和名称读取当前简历资料；更新时间来自关联荣誉库 */ (entry) => ({
      name: entry.title,
      date: entry.period,
      updatedAt: sources.get(entry.id)?.updated_at,
    }),
  );
  let index = 0;
  return section.entries.map(
    /* 保留非荣誉资料原来的位置 */ (entry) =>
      isHonorEntry(entry, section) ? entries[index++] : entry,
  );
}
