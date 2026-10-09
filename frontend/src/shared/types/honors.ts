import type { ImportTrace } from "./imports";

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

export interface Honor {
  id: string;
  fields: HonorFields;
  attachment: {
    name: string;
    size: number;
    pages: number;
    extension: string;
    text: string;
    importer?: ImportTrace;
    notices?: string[];
  } | null;
  status: "queued" | "running" | "review" | "ready" | "failed" | "cancelled";
  reviewed: boolean;
  recognition: { fields: HonorFields; text: string; warnings: string[] } | null;
  error: string;
  version: number;
  created_at: string;
  updated_at: string;
}
