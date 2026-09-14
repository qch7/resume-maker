import type {
  PersonalInfo,
  ResumeDocument,
  SectionEntry,
} from "../../shared/types/index.ts";

/** 按字段内容比较资料；显隐按集合处理，自定义信息保持用户排序。 */
function infoSnapshot(info?: PersonalInfo | SectionEntry) {
  if (!info) return null;
  const { hidden_fields, custom_fields, ...fields } = info;
  return [
    Object.entries(fields).sort(
      /* JSON 属性顺序不代表用户修改。 */ ([a], [b]) => a.localeCompare(b),
    ),
    [...new Set(hidden_fields)].sort(),
    custom_fields.map(
      /* 自定义信息顺序属于排版内容。 */ (field) => [
        field.id,
        field.label,
        field.value,
        field.visible,
      ],
    ),
  ];
}

/** 单条保存后按实际内容判断只读状态。 */
export function sameSectionEntry(a?: SectionEntry, b?: SectionEntry) {
  return JSON.stringify(infoSnapshot(a)) === JSON.stringify(infoSnapshot(b));
}

/** 按实际资料比较保存状态，忽略 JSON 属性顺序。 */
export function samePersonalInfo(a?: PersonalInfo, b?: PersonalInfo) {
  return JSON.stringify(infoSnapshot(a)) === JSON.stringify(infoSnapshot(b));
}

/** 比较完整资料，保留栏目、条目和自定义信息的顺序。 */
function documentSnapshot(document?: ResumeDocument | null) {
  if (!document) return null;
  return [
    infoSnapshot(document.personal),
    document.sections.map(
      /* 栏目顺序和归属属于真实修改，不能在比较时重新排序。 */ (section) => [
        section.id,
        section.title,
        section.kind,
        section.parent_id,
        section.visible,
        section.entries.map(infoSnapshot),
      ],
    ),
  ];
}

/** 保存标记和导出状态共用相同的资料比较规则。 */
export function sameResumeDocument(
  a?: ResumeDocument | null,
  b?: ResumeDocument | null,
) {
  return (
    JSON.stringify(documentSnapshot(a)) === JSON.stringify(documentSnapshot(b))
  );
}
