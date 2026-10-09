import type {
  DefaultSection,
  Resume,
  ResumeDefaults,
  ResumeDocument,
  ResumeSection,
} from "../../../shared/types/index.ts";

/** 优先按稳定标识匹配，旧简历中唯一同名同类型栏目沿用原标识 */
export function matchDefaultSections(
  sections: ResumeSection[],
  definitions: DefaultSection[],
  previous?: DefaultSection[],
) {
  const matches = new Map<string, ResumeSection>();
  const used = new Set<string>();
  for (const definition of definitions) {
    const exact = sections.find(
      /* 精确匹配优先于其他栏目的名称回退 */ (section) =>
        section.id === definition.id,
    );
    if (exact) {
      matches.set(definition.id, exact);
      used.add(exact.id);
    }
  }
  for (const definition of definitions) {
    if (matches.has(definition.id)) continue;
    const original = previous?.find(
      /* 改名或切换布局时仍能找到沿用旧标识的栏目 */ (item) =>
        item.id === definition.id,
    );
    const candidates = sections.filter(
      /* 项目区按类型识别，普通栏目使用本次或上次默认名称匹配 */ (section) =>
        !used.has(section.id) &&
        ((section.kind === definition.kind &&
          (definition.kind === "projects" ||
            section.title.trim() === definition.title.trim())) ||
          (original &&
            section.kind === original.kind &&
            section.title.trim() === original.title.trim())),
    );
    if (candidates.length > 1)
      throw new Error(
        `存在多个“${definition.title}”栏目，请先区分名称后再应用默认设置。`,
      );
    if (candidates.length === 1) {
      matches.set(definition.id, candidates[0]);
      used.add(candidates[0].id);
    }
  }
  return matches;
}

/** 只清理旧合并逻辑补入的同名空默认栏目，保留所有条目及其他草稿 */
export function repairDefaultDuplicates(
  document: ResumeDocument | null,
  defaults?: ResumeDefaults | null,
  saved?: ResumeDocument | null,
): ResumeDocument | null {
  if (!document || !defaults) return document;
  const replacements = new Map<string, ResumeSection>();
  const restoredParents = new Map<string, string>();
  for (const definition of defaults.sections) {
    const empty = document.sections.find(
      /* 只有带默认字段快照且完全没有条目的默认栏目属于修复范围 */ (section) =>
        section.id === definition.id &&
        section.kind !== "projects" &&
        section.kind === definition.kind &&
        section.title.trim() === definition.title.trim() &&
        section.field_definitions != null &&
        section.entries.length === 0,
    );
    if (!empty) continue;
    const candidates = document.sections.filter(
      /* 不合并明确配置的不同默认栏目、父子同名栏目或多个有内容的栏目 */ (
        section,
      ) =>
        !defaults.sections.some(
          /* 目标须为旧简历自行使用的标识 */ (item) => item.id === section.id,
        ) &&
        section.kind === empty.kind &&
        section.title.trim() === empty.title.trim() &&
        section.entries.length > 0 &&
        section.parent_id !== empty.id &&
        empty.parent_id !== section.id,
    );
    if (candidates.length !== 1) continue;
    const existing = candidates[0];
    if (
      existing.parent_id &&
      document.sections.some(
        /* 防止重挂子栏目后出现三级结构 */ (section) =>
          section.parent_id === empty.id,
      )
    )
      continue;
    replacements.set(empty.id, existing);
    const original = saved?.sections.find(
      /* 仅恢复旧逻辑错误提升的、已保存过的父级 */ (section) =>
        section.id === existing.id,
    );
    if (
      !existing.parent_id &&
      original?.parent_id &&
      original.parent_id === empty.parent_id
    )
      restoredParents.set(existing.id, original.parent_id);
  }
  if (!replacements.size) return document;
  const sections = document.sections
    .filter(
      /* 只删除没有正文的空默认栏目 */ (section) =>
        !replacements.has(section.id),
    )
    .map(
      /* 重挂空栏目下的子栏目，保持条目标识和当前排列 */ (section) => {
        const parent = restoredParents.get(section.id) ?? section.parent_id;
        const parent_id = parent
          ? (replacements.get(parent)?.id ?? parent)
          : null;
        return parent_id === section.parent_id
          ? section
          : { ...section, parent_id };
      },
    );
  return { ...document, sections };
}

/** 保留未变化对象的引用以避免轮询触发草稿更新 */
export function repairDefaultResume(
  resume: Resume,
  defaults?: ResumeDefaults | null,
  saved?: Resume,
) {
  const document = repairDefaultDuplicates(
    resume.document,
    defaults,
    saved?.document,
  );
  return document === resume.document ? resume : { ...resume, document };
}
