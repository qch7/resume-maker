import type {
  DefaultSection,
  ResumeDefaults,
  ResumeDocument,
} from "../../shared/types/index.ts";
import { matchDefaultSections } from "./defaultSections.ts";

/** 按父子层级展开栏目，同级沿用原顺序，缺失父级的栏目仍可编辑。 */
function sectionOrder<T extends { id: string; parent_id?: string | null }>(
  sections: T[],
): T[] {
  const result: T[] = [];
  const visited = new Set<string>();
  /** 每个栏目只进入一次，兼容旧数据中无效的父级关系。 */
  function append(section: T) {
    if (visited.has(section.id)) return;
    visited.add(section.id);
    result.push(section);
    for (const child of sections)
      if (child.parent_id === section.id) append(child);
  }
  for (const section of sections) if (!section.parent_id) append(section);
  for (const section of sections) append(section);
  return result;
}

/** 默认栏目跟随当前编排，兼容旧标识；尚未使用的默认栏目排在同级末尾。 */
export function orderDefaultSections(
  definitions: DefaultSection[],
  document: ResumeDocument | null = null,
): DefaultSection[] {
  if (!document) return sectionOrder(definitions);
  let matches;
  try {
    matches = matchDefaultSections(document.sections, definitions);
  } catch {
    // 有同名歧义时仅同步标识确定的栏目，不妨碍用户进入设置修正名称。
    matches = new Map(
      definitions.flatMap(
        /* 不根据含糊的名称猜测顺序。 */ (definition) => {
          const section = document.sections.find(
            /* 精确标识不会误认同名栏目。 */ (item) =>
              item.id === definition.id,
          );
          return section ? [[definition.id, section] as const] : [];
        },
      ),
    );
  }
  const byResumeId = new Map(
    definitions.map(
      /* 定义保留原标识，只借用当前简历的排列。 */ (definition) => [
        matches.get(definition.id)?.id ?? definition.id,
        definition,
      ],
    ),
  );
  const ordered = sectionOrder(document.sections).flatMap(
    /* 当前简历的临时栏目不自动加入全局默认配置。 */ (section) => {
      const definition = byResumeId.get(section.id);
      return definition ? [definition] : [];
    },
  );
  const used = new Set(
    ordered.map(/* 每个默认栏目只展示一次。 */ (section) => section.id),
  );
  return sectionOrder([
    ...ordered,
    ...definitions.filter(
      /* 新增或尚未采用的定义仍可在设置中找到。 */ (section) =>
        !used.has(section.id),
    ),
  ]);
}

export type DefaultSearchResult = {
  sectionId: string;
  fieldId?: string;
  title: string;
  sectionTitle: string;
};

/** 按导航顺序搜索栏目及信息项，支持跨栏目的多个关键词和英文大小写。 */
export function searchDefaultFields(
  defaults: ResumeDefaults,
  query: string,
): DefaultSearchResult[] {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const groups = [
    { id: "personal", title: "个人信息", fields: defaults.personal_fields },
    ...orderDefaultSections(defaults.sections),
  ];
  const results: DefaultSearchResult[] = [];
  for (const group of groups) {
    const sectionTitle = group.title || "未命名栏目";
    if (
      terms.every(
        /* 栏目名独立匹配。 */ (term) =>
          sectionTitle.toLocaleLowerCase().includes(term),
      )
    )
      results.push({ sectionId: group.id, title: sectionTitle, sectionTitle });
    for (const field of group.fields) {
      const text = `${sectionTitle} ${field.label}`.toLocaleLowerCase();
      if (
        terms.every(
          /* 信息项可同时按所属栏目缩小范围。 */ (term) => text.includes(term),
        )
      )
        results.push({
          sectionId: group.id,
          fieldId: field.id,
          title: field.label,
          sectionTitle,
        });
    }
  }
  return results;
}
