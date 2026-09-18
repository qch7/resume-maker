export const CATEGORIES = [
  "竞赛获奖",
  "资格证书",
  "奖学金",
  "荣誉称号",
  "其他",
] as const;
export type HonorCategory = (typeof CATEGORIES)[number];
export interface HonorFields {
  name: string;
  category: HonorCategory;
  level: string;
  award: string;
  issuer: string;
  date: string;
  recipient: string;
  certificate_number: string;
  description: string;
}

export interface HonorSource {
  id: string;
  fields: HonorFields;
  reviewed: boolean;
  version: number;
  updated_at: string;
}
