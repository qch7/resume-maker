import type { ResumeDocument } from "../../shared/types/index.ts";
import type { TemplateNode, TextBinding } from "./types.ts";

export const PERSONAL_LABELS: Record<string, string> = {
  "personal.name": "姓名",
  "personal.job_title": "求职意向",
  "personal.gender": "性别",
  "personal.age": "年龄",
  "personal.phone": "电话",
  "personal.email": "邮箱",
  "personal.gpa": "专业成绩",
  "personal.location": "所在地",
  "personal.website": "个人主页",
  "personal.custom_fields": "全部自定义信息",
};
export const ENTRY_LABELS: Record<string, string> = {
  title: "学校 / 项目 / 条目名称",
  subtitle: "专业 / 学历 / 副标题",
  period: "时间",
  details: "全部正文",
  role: "项目角色",
  stack: "技术栈",
  description: "项目描述",
  highlights: "选中亮点",
  custom_fields: "自定义信息",
};

/** 生成用户当前可以映射的资料字段和栏目标题名称。 */
export function personalTargets(document: ResumeDocument) {
  return {
    ...PERSONAL_LABELS,
    ...Object.fromEntries(
      document.personal.custom_fields.map(
        /* 自定义字段按名称匹配，可复用于另一份同名资料。 */ (field) => [
          `personal.custom:${field.label}`,
          field.label,
        ],
      ),
    ),
    ...Object.fromEntries(
      document.sections.map(
        /* 栏目标题可以跟随同名资料栏目填入。 */ (section) => [
          `section-title:${section.title}`,
          `${section.title} · 栏目标题`,
        ],
      ),
    ),
  };
}

/** 新增映射从明确的原文开始，保存前仍需校验具体字段和引文。 */
export function newBinding(node: TemplateNode, target: string): TextBinding {
  return { node: node.id, quote: node.text, target, occurrence: 1 };
}

/** 位置选项只展示用户可理解的容器和原文，不暴露 XML 路径。 */
export function nodeLabel(node: TemplateNode) {
  const part = node.part.includes("header")
    ? "页眉"
    : node.part.includes("footer")
      ? "页脚"
      : node.part.includes("footnotes")
        ? "脚注"
        : node.part.includes("endnotes")
          ? "尾注"
          : "正文";
  const kind =
    node.kind === "tr"
      ? "表格行"
      : node.kind === "tbl"
        ? "表格"
        : node.kind === "image"
          ? "图片"
          : "段落";
  return `${part} · ${kind} · ${node.text.slice(0, 65) || (node.can_insert ? "空白" : "内容容器")}`;
}
