import type {
  ResumeDocument,
  ResumeSection,
  SectionEntry,
} from "../../shared/types/index.ts";
import { isHonorEntry, isHonorSection } from "../honors/entry.ts";

/** 技能栏目允许改名，默认标识和常见名称共用同一定位规则 */
export function isSkillsSection(section: ResumeSection) {
  return (
    section.kind === "text" &&
    (section.id === "skills" || /技能|专长/.test(section.title))
  );
}

/** 只统计有可见内容的条目 */
function hasEntryContent(entry: SectionEntry) {
  return (
    entry.visible &&
    ((["title", "subtitle", "period", "details"] as const).some(
      /* 只采纳实际输出到简历的字段 */ (key) =>
        !entry.hidden_fields.includes(key) && !!entry[key].trim(),
    ) ||
      entry.custom_fields.some(
        /* 自定义内容同样可以构成有效资料 */ (field) =>
          field.visible && !!field.value.trim(),
      ))
  );
}

/** 连同父栏目检查显隐，隐藏或移除的可选栏目不阻碍后续制作 */
export function visibleSections(document?: ResumeDocument | null) {
  const sections = document?.sections ?? [];
  return sections.filter(
    /* 向上检查栏目祖先并防止异常层级循环 */ (section) => {
      let current: ResumeSection | undefined = section;
      const visited = new Set<string>();
      while (current) {
        if (!current.visible || visited.has(current.id)) return false;
        visited.add(current.id);
        const parent: string | null = current.parent_id;
        current = sections.find(
          /* 查找当前栏目的父级 */ (item) => item.id === parent,
        );
      }
      return true;
    },
  );
}

/** 根据整份简历的可见资料计算准备状态 */
export function getProfileProgress(document?: ResumeDocument | null) {
  const personal = document?.personal;
  const sections = visibleSections(document);
  const education = sections.filter(
    /* 按栏目类型识别教育信息 */ (section) => section.kind === "education",
  );
  const skills = sections.filter(isSkillsSection);
  const honors = sections.filter(isHonorSection);
  /** 已移除或隐藏的可选栏目视为无需填写，有栏目时必须存在有效内容 */
  function ready(group: ResumeSection[]) {
    return (
      !!document &&
      (!group.length ||
        group.some(
          /* 至少填写一条可见资料 */ (section) =>
            section.entries.some(hasEntryContent),
        ))
    );
  }
  const selectedHonor = sections.some(
    /* 荣誉即使移动到自定义栏目，仍按来源标识识别 */ (section) =>
      section.entries.some(
        /* 手动录入和荣誉库引用都属于有效简历内容 */ (entry) =>
          isHonorEntry(entry, section) && hasEntryContent(entry),
      ),
  );
  return {
    basic:
      !!personal?.name.trim() &&
      !personal.hidden_fields.includes("name") &&
      ((!!personal.phone.trim() && !personal.hidden_fields.includes("phone")) ||
        (!!personal.email.trim() && !personal.hidden_fields.includes("email"))),
    education: ready(education),
    skills: ready(skills),
    honors: selectedHonor || (!!document && !honors.length),
    selectedHonor,
  };
}
