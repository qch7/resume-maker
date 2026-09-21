import { applyInfoDefaults } from "../profile/defaults/model.ts";
import type { ResumeDocument, SectionEntry } from "../../shared/types/index.ts";

import type { HonorFields } from "./fields.ts";
import { isHonorSection, newHonorEntry } from "./entry.ts";
export { CATEGORIES, emptyHonor } from "./fields.ts";
export type { HonorCategory, HonorFields } from "./fields.ts";

export interface Honor {
  id: string;
  fields: HonorFields;
  attachment: {
    name: string;
    size: number;
    pages: number;
    extension: string;
    text: string;
  } | null;
  status: "queued" | "running" | "review" | "ready" | "failed" | "cancelled";
  reviewed: boolean;
  recognition: { fields: HonorFields; text: string; warnings: string[] } | null;
  error: string;
  version: number;
  created_at: string;
  updated_at: string;
}
export const STATUS = {
  queued: "等待识别",
  running: "识别中",
  review: "待核对",
  ready: "已核对",
  failed: "识别失败",
  cancelled: "未完成识别",
};
export const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff";

/** 识别期间禁用人工编辑以防结果覆盖未保存内容 */
export function isRecognizing(honor: Honor) {
  return honor.status === "queued" || honor.status === "running";
}

/** 按名称、单位、获奖人和编号等荣誉资料检索 */
export function matchesHonor(honor: Honor, query: string) {
  return [...Object.values(honor.fields), honor.attachment?.name ?? ""]
    .join(" ")
    .toLocaleLowerCase()
    .includes(query.trim().toLocaleLowerCase());
}

/** 检查荣誉是否已复制进当前简历，跨栏目去重 */
export function hasHonor(document: ResumeDocument | null, id: string) {
  return (
    document?.sections.some(
      /* 检查所有栏目中的稳定来源标识 */ (section) =>
        section.entries.some(
          /* 同一荣誉仅加入一次 */ (entry) => entry.id === `honor:${id}`,
        ),
    ) ?? false
  );
}

/** 仅移除当前简历中的荣誉引用，保留栏目、其他资料及库中原件 */
export function removeHonor(
  document: ResumeDocument,
  id: string,
): ResumeDocument {
  if (!hasHonor(document, id)) return document;
  return {
    ...document,
    sections: document.sections.map(
      /* 按来源标识移除条目以支持自定义栏目 */ (section) => {
        const entries = section.entries.filter(
          /* 同名手动条目和其他来源均保留 */ (entry) =>
            entry.id !== `honor:${id}`,
        );
        return entries.length === section.entries.length
          ? section
          : { ...section, entries };
      },
    ),
  };
}

/** 将已核对荣誉关联到简历，初始内容完整复制，后续按来源同步 */
export function addHonors(
  document: ResumeDocument,
  honors: Honor[],
  target = "",
): ResumeDocument {
  const additions: SectionEntry[] = honors
    .filter(
      /* 只采用已核对且尚未加入的条目 */ (honor) =>
        honor.reviewed &&
        honor.status === "ready" &&
        honor.fields.name.trim() &&
        !hasHonor(document, honor.id),
    )
    .map(
      /* 完整保留各项荣誉资料，默认只显示名称和日期 */ (honor) =>
        newHonorEntry(honor.fields, `honor:${honor.id}`),
    );
  if (!additions.length) return document;
  const section = target
    ? document.sections.find(
        /* 显式目标必须仍然存在 */ (item) =>
          item.id === target && item.kind === "text",
      )
    : document.sections.find(isHonorSection);
  if (target && !section) throw new Error("目标栏目已不存在，请重新选择。");
  if (section && section.entries.length + additions.length > 100)
    throw new Error("此栏目最多容纳 100 条，请选择其他栏目。");
  if (!section && document.sections.length >= 40)
    throw new Error("栏目数量已达上限，请选择已有栏目。");
  return {
    ...document,
    sections: section
      ? document.sections.map(
          /* 保留其他栏目和当前顺序 */ (item) =>
            item.id === section.id
              ? {
                  ...item,
                  entries: [
                    ...item.entries,
                    ...additions.map(
                      /* 新加入荣誉沿用目标栏目的默认字段 */ (entry) =>
                        item.field_definitions
                          ? applyInfoDefaults(
                              entry,
                              item.field_definitions,
                              true,
                            )
                          : entry,
                    ),
                  ],
                }
              : item,
        )
      : [
          ...document.sections,
          {
            id: crypto.randomUUID(),
            title: "荣誉证书",
            kind: "text",
            parent_id: null,
            visible: true,
            entries: additions,
          },
        ],
  };
}
