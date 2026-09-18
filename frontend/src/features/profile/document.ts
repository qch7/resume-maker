import type {
  CustomInfoField,
  PersonalInfo,
  ResumeDocument,
  ResumeSection,
  SectionEntry,
  DefaultField,
  ResumeDefaults,
} from "../../shared/types/index.ts";
import { applyInfoDefaults, applyResumeDefaults } from "./defaults.ts";

/** 为新方案生成独立资料；主修课程默认归入教育背景，项目经历保持大栏目。 */
export function newDocument(defaults?: ResumeDefaults | null): ResumeDocument {
  const document: ResumeDocument = {
    personal: {
      name: "",
      job_title: "",
      gender: "",
      age: "",
      phone: "",
      email: "",
      gpa: "",
      location: "",
      website: "",
      photo: "",
      hidden_fields: [],
      custom_fields: [],
    },
    sections: [
      {
        id: "education",
        title: "教育背景",
        kind: "education",
        parent_id: null,
        visible: true,
        entries: [],
      },
      {
        id: "courses",
        title: "主修课程",
        kind: "text",
        parent_id: "education",
        visible: true,
        entries: [],
      },
      {
        id: "projects",
        title: "项目经历",
        kind: "projects",
        parent_id: null,
        visible: true,
        entries: [],
      },
      {
        id: "honors",
        title: "荣誉证书",
        kind: "text",
        parent_id: null,
        visible: true,
        entries: [],
      },
      {
        id: "skills",
        title: "专业技能",
        kind: "text",
        parent_id: null,
        visible: true,
        entries: [],
      },
    ],
  };
  return defaults ? applyResumeDefaults(document, defaults) : document;
}

/** 创建独立的空条目，输入内容后自动参与预览与导出。 */
export function newEntry(definitions?: DefaultField[] | null): SectionEntry {
  const entry: SectionEntry = {
    id: crypto.randomUUID(),
    title: "",
    subtitle: "",
    period: "",
    details: "",
    visible: true,
    hidden_fields: [],
    custom_fields: [],
  };
  return definitions ? applyInfoDefaults(entry, definitions, true) : entry;
}

/** 按父栏目提取同级条目，数组顺序就是排版顺序。 */
export function siblings(
  sections: ResumeSection[],
  parent: string | null = null,
) {
  return sections.filter(
    /* 仅选取指定层级。 */ (section) => section.parent_id === parent,
  );
}

/** 在同一层级交换顺序，子栏目始终跟随父栏目展示。 */
export function moveSection(
  sections: ResumeSection[],
  parent: string | null,
  from: number,
  to: number,
) {
  const group = siblings(sections, parent);
  if (from < 0 || to < 0 || from >= group.length || to >= group.length)
    return sections;
  const [moved] = group.splice(from, 1);
  group.splice(to, 0, moved);
  let index = 0;
  return sections.map(
    /* 只更新同级所占的位置，保留其他栏目。 */ (section) =>
      section.parent_id === parent ? group[index++] : section,
  );
}

/** 删除栏目时把子栏目提升为独立大栏目，防止连带丢失其他资料。 */
export function removeSection(sections: ResumeSection[], id: string) {
  return sections
    .filter(
      /* 项目区只允许隐藏。 */ (section) =>
        section.id !== id || section.kind === "projects",
    )
    .map(
      /* 子栏目恢复为顶级。 */ (section) =>
        section.parent_id === id ? { ...section, parent_id: null } : section,
    );
}

/** 只在排版副本中清空隐藏字段，原始个人资料保留以便恢复。 */
export function displayedPersonal(personal: PersonalInfo): PersonalInfo {
  const displayed = { ...personal };
  for (const field of personal.hidden_fields) displayed[field] = "";
  displayed.custom_fields = visibleCustomFields(personal.custom_fields);
  return displayed;
}

/** 创建可命名的独立信息项，空名称和空内容不会进入成品。 */
export function newCustomField(): CustomInfoField {
  return { id: crypto.randomUUID(), label: "", value: "", visible: true };
}

/** 按添加顺序展示填写完整且未隐藏的自定义信息，保持原数据可编辑。 */
export function visibleCustomFields(fields: CustomInfoField[]) {
  return fields
    .filter(
      /* 空白和隐藏的信息项不占用排版位置。 */ (field) =>
        field.visible && field.label.trim() && field.value.trim(),
    )
    .map(
      /* 只修剪排版副本的首尾空白。 */ (field) => ({
        ...field,
        label: field.label.trim(),
        value: field.value.trim(),
      }),
    );
}

/** 切换字段显隐，保留字段值；再次点击可恢复显示。 */
export function toggleHiddenField<T extends string>(
  hidden: T[],
  field: T,
): T[] {
  return hidden.includes(field)
    ? hidden.filter(/* 仅移除本次恢复的字段。 */ (item) => item !== field)
    : [...hidden, field];
}

/** 生成可见条目副本，去掉与栏目重名的文本标题和没有正文的空条目。 */
export function filledEntries(section: ResumeSection) {
  return section.entries
    .filter(/* 隐藏整条资料时保留原文但不参与排版。 */ (entry) => entry.visible)
    .map(
      /* 字段显隐与标题去重只作用于排版副本。 */ (entry) => {
        const displayed = { ...entry };
        for (const field of entry.hidden_fields) displayed[field] = "";
        displayed.custom_fields = visibleCustomFields(entry.custom_fields);
        if (
          section.kind === "text" &&
          displayed.title.trim() === section.title.trim()
        )
          displayed.title = "";
        return displayed;
      },
    )
    .filter(
      /* 至少有一项实际内容。 */ (entry) =>
        [entry.title, entry.subtitle, entry.period, entry.details].some(
          /* 忽略空格。 */ (value) => value.trim(),
        ) || entry.custom_fields.length > 0,
    );
}

/** 判断大栏目是否有可见正文，隐藏子栏目不影响成品排版。 */
export function hasSectionContent(
  section: ResumeSection,
  sections: ResumeSection[],
  projectCount: number,
) {
  if (!section.visible) return false;
  return (
    (section.kind === "projects" && projectCount > 0) ||
    filledEntries(section).length > 0 ||
    siblings(sections, section.id).some(
      /* 子栏目按自身显隐决定是否贡献正文。 */ (child) =>
        child.visible && filledEntries(child).length > 0,
    )
  );
}
