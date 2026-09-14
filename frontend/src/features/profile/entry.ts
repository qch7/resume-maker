import type {
  Resume,
  ResumeDocument,
  ResumeSection,
} from "../../shared/types/index.ts";
import { newDocument } from "./document.ts";

/** 按栏目和条目标识读取资料，避免排序后保存到其他经历。 */
export function findEntry(
  document: ResumeDocument | null | undefined,
  sectionId: string,
  entryId: string,
) {
  return document?.sections
    .find(/* 定位栏目。 */ (section) => section.id === sectionId)
    ?.entries.find(/* 定位条目。 */ (entry) => entry.id === entryId);
}

/** 单条保存只采用该条内容；新栏目仅补入必要层级，其他资料保留服务器版本。 */
export function entryComposition(
  draft: Resume,
  saved: Resume | undefined,
  sectionId: string,
  entryId: string,
): Resume {
  if (draft.id && !saved)
    throw new Error("当前方案已不存在，请刷新后重新选择。");
  const entry = findEntry(draft.document, sectionId, entryId);
  const source = draft.document?.sections.find(
    /* 定位待保存的栏目。 */ (section) => section.id === sectionId,
  );
  if (!entry || !source || source.kind === "projects")
    throw new Error("这条资料已不存在，请刷新后重试。");
  const baseline = saved ?? { ...draft, items: [], document: newDocument() };
  const document = baseline.document ?? newDocument();
  const sections = [...document.sections];
  /** 递归补齐新栏目的父级，只保存结构，不带入其他条目草稿。 */
  function ensureSection(section: ResumeSection): void {
    if (
      sections.some(
        /* 已保存栏目保持原有结构。 */ (item) => item.id === section.id,
      )
    )
      return;
    if (section.parent_id) {
      const parent = draft.document?.sections.find(
        /* 读取新栏目的父级。 */ (item) => item.id === section.parent_id,
      );
      if (!parent || parent.parent_id)
        throw new Error("栏目层级无效，请先调整栏目。");
      ensureSection(parent);
    }
    sections.push({ ...section, entries: [] });
  }
  ensureSection(source);
  return {
    ...baseline,
    id: draft.id,
    version: draft.version,
    template_id: draft.template_id,
    document: {
      ...document,
      sections: sections.map(
        /* 仅替换或追加本次保存的条目。 */ (section) => {
          if (section.id !== sectionId) return section;
          if (section.kind === "projects")
            throw new Error("栏目类型已变化，请先保存栏目编排。");
          const exists = section.entries.some(
            /* 保留已有条目的排序。 */ (item) => item.id === entryId,
          );
          return {
            ...section,
            entries: exists
              ? section.entries.map(
                  /* 同一条目原位更新。 */ (item) =>
                    item.id === entryId ? entry : item,
                )
              : [...section.entries, entry],
          };
        },
      ),
    },
  };
}
