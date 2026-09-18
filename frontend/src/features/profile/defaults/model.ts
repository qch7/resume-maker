import type {
  CustomInfoField,
  DefaultField,
  DefaultSection,
  Experience,
  PersonalInfo,
  ResumeDefaults,
  ResumeDocument,
  ResumeSection,
  SectionEntry,
} from "../../../shared/types/index.ts";
import { matchDefaultSections, repairDefaultDuplicates } from "./sections.ts";

/** 判断删除默认项是否涉及已填写内容；隐藏但有值的字段也必须确认 */
export function defaultHasContent(
  document: ResumeDocument | null,
  sectionId: string,
  fieldId?: string,
  projects: Experience[] = [],
  definition?: DefaultSection,
): boolean {
  const sections =
    document?.sections.filter(
      /* 旧简历同名栏目沿用原标识；删除前仍须检查其中的填写内容 */ (item) =>
        item.id === sectionId ||
        (definition &&
          item.kind === definition.kind &&
          item.title.trim() === definition.title.trim()),
    ) ?? [];
  const records =
    sectionId === "personal"
      ? [document?.personal]
      : sections.some(
            /* 项目原文从版本中读取 */ (section) => section.kind === "projects",
          )
        ? projects
        : sections.flatMap(
            /* 存在同名歧义时也不得跳过有值确认 */ (section) => section.entries,
          );
  return records.some(
    /* 任一条资料有内容即触发二次确认 */ (record) => {
      if (!record) return false;
      if (fieldId?.includes(":"))
        return !!record.custom_fields?.some(
          /* 默认自定义项按稳定标识读取 */ (field) =>
            field.id === fieldId && field.value.trim(),
        );
      if (fieldId) {
        const value = (record as unknown as Record<string, unknown>)[fieldId];
        return Array.isArray(value)
          ? value.length > 0
          : typeof value === "string" && !!value.trim();
      }
      return Object.entries(record).some(
        /* 排除标识和配置且只检查正文 */ ([key, value]) =>
          !["id", "hidden_fields", "field_definitions", "body_order"].includes(
            key,
          ) &&
          (typeof value === "string"
            ? !!value.trim()
            : key === "custom_fields"
              ? record.custom_fields?.some(
                  /* 空白默认项不算内容 */ (field) => !!field.value.trim(),
                )
              : key === "highlights" &&
                Array.isArray(value) &&
                value.length > 0),
      );
    },
  );
}

/** 将内置字段的语义标识与中文名称转换为可编辑定义 */
function fields(items: [string, string][]): DefaultField[] {
  return items.map(
    /* 每次生成独立定义以免表单编辑污染内置配置 */ ([id, label]) => ({
      id,
      label,
      visible: true,
    }),
  );
}
export const PERSONAL_FIELDS = fields([
  ["name", "姓名"],
  ["job_title", "求职意向"],
  ["gender", "性别"],
  ["age", "年龄"],
  ["phone", "电话"],
  ["email", "邮箱"],
  ["gpa", "专业成绩"],
  ["location", "所在地"],
  ["website", "个人主页"],
  ["photo", "照片"],
]);
export const PROJECT_FIELDS = fields([
  ["title", "项目标题"],
  ["period", "参与时间"],
  ["role", "担任角色"],
  ["stack", "技术栈"],
  ["description", "项目描述"],
]);
export const TEXT_FIELDS = fields([
  ["title", "标题"],
  ["subtitle", "补充信息"],
  ["period", "时间"],
  ["details", "详细内容"],
]);
export const EDUCATION_FIELDS = fields([
  ["title", "学校名称"],
  ["subtitle", "专业 / 学历"],
  ["period", "在校时间"],
  ["details", "补充说明"],
]);
export const HONOR_DEFAULT_FIELDS = fields([
  ["title", "荣誉名称"],
  ["period", "获得日期"],
  ["subtitle", "颁发单位"],
  ["details", "荣誉说明"],
  ["honor-field:award", "奖项"],
  ["honor-field:level", "荣誉级别"],
  ["honor-field:recipient", "获奖人"],
  ["honor-field:certificate_number", "证书编号"],
  ["honor-field:category", "分类"],
]).map(
  /* 荣誉最初仅名称和日期参与排版 */ (field) => ({
    ...field,
    visible: ["title", "period"].includes(field.id),
  }),
);

/** 未配置的栏目沿用其类型的内置字段 */
export function builtinFields(
  section?: Pick<ResumeSection, "id" | "title" | "kind">,
): DefaultField[] {
  if (!section) return PERSONAL_FIELDS;
  if (section.kind === "projects") return PROJECT_FIELDS;
  if (section.kind === "education") return EDUCATION_FIELDS;
  return section.id === "honors" || /荣誉|获奖|证书/.test(section.title)
    ? HONOR_DEFAULT_FIELDS
    : TEXT_FIELDS;
}

/** 提供独立的内置默认配置；保存设置之前不依赖网络请求 */
export function builtinDefaults(): ResumeDefaults {
  const sections: DefaultSection[] = [
    {
      id: "education",
      title: "教育背景",
      kind: "education",
      parent_id: null,
      visible: true,
      fields: EDUCATION_FIELDS,
    },
    {
      id: "courses",
      title: "主修课程",
      kind: "text",
      parent_id: "education",
      visible: true,
      fields: TEXT_FIELDS,
    },
    {
      id: "projects",
      title: "项目经历",
      kind: "projects",
      parent_id: null,
      visible: true,
      fields: PROJECT_FIELDS,
    },
    {
      id: "honors",
      title: "荣誉证书",
      kind: "text",
      parent_id: null,
      visible: true,
      fields: HONOR_DEFAULT_FIELDS,
    },
    {
      id: "skills",
      title: "专业技能",
      kind: "text",
      parent_id: null,
      visible: true,
      fields: TEXT_FIELDS,
    },
  ];
  return structuredClone({
    version: 0,
    personal_fields: PERSONAL_FIELDS,
    sections,
  });
}

/** 未设置定义的旧资料继续展示内置字段 */
export function hasDefault(
  definitions: DefaultField[] | null | undefined,
  id: string,
) {
  return (
    definitions == null ||
    definitions.some(/* 稳定标识不受重命名影响 */ (field) => field.id === id)
  );
}

/** 字段重命名只影响界面标签；保存值仍使用原有语义键 */
export function defaultLabel(
  definitions: DefaultField[] | null | undefined,
  id: string,
  fallback: string,
) {
  return (
    definitions?.find(/* 按语义标识查找用户配置 */ (field) => field.id === id)
      ?.label ?? fallback
  );
}

/** 合并默认自定义项并保留已填写的已删除项；后者隐藏且不再出现在表单中 */
export function applyCustomDefaults(
  existing: CustomInfoField[],
  definitions: DefaultField[],
  previous?: DefaultField[] | null,
) {
  const result = existing.flatMap(
    /* 普通临时字段不参与默认项删除 */ (field) => {
      const definition = definitions.find(
        /* 默认项以稳定标识匹配已有值 */ (item) => item.id === field.id,
      );
      if (!definition)
        return field.id.startsWith("default:") ||
          field.id.startsWith("honor-field:")
          ? field.value
            ? [{ ...field, visible: false }]
            : []
          : [field];
      const old = previous?.find(
        /* 只有默认显隐改变才覆盖当前选择 */ (item) => item.id === field.id,
      );
      return [
        {
          ...field,
          label: definition.label,
          visible:
            old && old.visible !== definition.visible
              ? definition.visible
              : field.visible,
        },
      ];
    },
  );
  for (const definition of definitions) {
    if (!definition.id.includes(":")) continue;
    if (
      !result.some(
        /* 已有字段的内容原样保留 */ (field) => field.id === definition.id,
      )
    )
      result.push({ ...definition, value: "" });
  }
  if (
    result.filter(
      /* 荣誉固定项不占用自定义项名额 */ (field) =>
        !field.id.startsWith("honor-field:"),
    ).length > 20
  )
    throw new Error(
      "部分资料已有较多自定义信息，加入默认项后超过 20 项。请先减少自定义信息后再保存。",
    );
  return result;
}

/** 应用字段结构时只调整显隐和定义；保留所有已填写内容 */
export function applyInfoDefaults<T extends PersonalInfo | SectionEntry>(
  info: T,
  definitions: DefaultField[],
  initialize = false,
): T {
  const keys = "name" in info ? PERSONAL_FIELDS : TEXT_FIELDS;
  const hidden = new Set<string>(info.hidden_fields);
  for (const key of keys) {
    const definition = definitions.find(
      /* 查找仍启用的固定字段 */ (field) => field.id === key.id,
    );
    const previous = info.field_definitions?.find(
      /* 识别本次改变的默认显隐 */ (field) => field.id === key.id,
    );
    if (!definition) hidden.add(key.id);
    else if (
      initialize ||
      !info.field_definitions ||
      !previous ||
      previous.visible !== definition.visible
    ) {
      if (!definition.visible) hidden.add(key.id);
      else if (initialize || info.field_definitions) hidden.delete(key.id);
    }
  }
  return {
    ...info,
    field_definitions: structuredClone(definitions),
    hidden_fields: [...hidden],
    custom_fields: applyCustomDefaults(
      initialize
        ? info.custom_fields.map(
            /* 新条目使用配置的初始显隐 */ (field) => ({
              ...field,
              visible:
                definitions.find(
                  /* 匹配默认定义 */ (item) => item.id === field.id,
                )?.visible ?? field.visible,
            }),
          )
        : info.custom_fields,
      definitions,
      info.field_definitions,
    ),
  } as T;
}

/** 把新配置应用于当前简历；移除栏目时保留有内容的资料并隐藏 */
export function applyResumeDefaults(
  document: ResumeDocument,
  defaults: ResumeDefaults,
  previous = builtinDefaults(),
): ResumeDocument {
  document = repairDefaultDuplicates(
    repairDefaultDuplicates(document, previous),
    defaults,
  )!;
  const matches = matchDefaultSections(
    document.sections,
    defaults.sections,
    previous.sections,
  );
  const previousIds = new Set(
    [
      ...matchDefaultSections(document.sections, previous.sections).values(),
    ].map(/* 沿用旧标识的默认栏目也参与移除判断 */ (section) => section.id),
  );
  const used = new Set(
    [...matches.values()].map(
      /* 旧栏目的标识已被复用；末尾不再重复追加 */ (section) => section.id,
    ),
  );
  const sections = defaults.sections.map(
    /* 默认栏目采用配置顺序并保留现有条目 */ ({ fields, ...definition }) => {
      const existing = matches.get(definition.id);
      return {
        ...definition,
        id: existing?.id ?? definition.id,
        parent_id: definition.parent_id
          ? (matches.get(definition.parent_id)?.id ?? definition.parent_id)
          : null,
        field_definitions: structuredClone(fields),
        entries: (existing?.entries ?? []).map(
          /* 每条资料分别保留自己的值 */ (entry) =>
            applyInfoDefaults(entry, fields),
        ),
      };
    },
  );
  for (const section of document.sections) {
    if (used.has(section.id) || section.kind === "projects") continue;
    const removed = previousIds.has(section.id);
    if (!removed || section.entries.length)
      sections.push({
        ...section,
        parent_id: section.parent_id,
        visible: removed ? false : section.visible,
        field_definitions: section.field_definitions ?? builtinFields(section),
      });
  }
  for (const section of sections) {
    if (!section.parent_id) continue;
    const parent = sections.find(
      /* 仅在父栏目已移除或变成子栏目时提升；保留有效的自定义层级 */ (item) =>
        item.id === section.parent_id,
    );
    if (!parent || parent.parent_id) section.parent_id = null;
  }
  if (sections.length > 40)
    throw new Error("应用默认设置后超过 40 个栏目，请先减少栏目。");
  return {
    ...document,
    personal: applyInfoDefaults(document.personal, defaults.personal_fields),
    sections,
  };
}
