import type { HonorFields } from "../../shared/types/honors.ts";
export { CATEGORIES } from "../../shared/types/honors.ts";
export type { HonorFields, HonorCategory } from "../../shared/types/honors.ts";

export interface HonorField {
  key: keyof HonorFields;
  label: string;
  placeholder: string;
  max: number;
}

// 荣誉库和个人信息共用字段说明，名称与奖项保持独立。
export const HONOR_FIELDS: HonorField[] = [
  {
    key: "name",
    label: "荣誉名称",
    placeholder: "例如：全国大学生数学建模竞赛",
    max: 300,
  },
  {
    key: "award",
    label: "奖项",
    placeholder: "例如：一等奖、金奖",
    max: 200,
  },
  {
    key: "level",
    label: "荣誉级别",
    placeholder: "例如：国家级、省级、校级",
    max: 100,
  },
  {
    key: "issuer",
    label: "颁发单位",
    placeholder: "证书上标注的主办或认证机构",
    max: 500,
  },
  {
    key: "date",
    label: "获得日期",
    placeholder: "例如：2026-06 或 2026",
    max: 100,
  },
  {
    key: "recipient",
    label: "获奖人",
    placeholder: "证书上标注的姓名或团队",
    max: 300,
  },
  {
    key: "certificate_number",
    label: "证书编号",
    placeholder: "没有编号可留空",
    max: 300,
  },
  { key: "category", label: "分类", placeholder: "", max: 100 },
  {
    key: "description",
    label: "荣誉说明",
    placeholder: "补充获奖项目、证书用途或其他备注",
    max: 5000,
  },
];

/** 创建独立的空白荣誉资料。 */
export function emptyHonor(): HonorFields {
  return {
    name: "",
    category: "其他",
    level: "",
    award: "",
    issuer: "",
    date: "",
    recipient: "",
    certificate_number: "",
    description: "",
  };
}
