import type { ResumeDocument, SectionEntry } from "../../shared/types/index.ts";

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

/** 识别状态决定能否人工编辑，避免在途结果覆盖未保存内容。 */
export function isRecognizing(honor: Honor) {
  return honor.status === "queued" || honor.status === "running";
}

/** 按名称、单位、获奖人和编号等资料检索，不依赖隐藏的本机路径。 */
export function matchesHonor(honor: Honor, query: string) {
  return [...Object.values(honor.fields), honor.attachment?.name ?? ""]
    .join(" ")
    .toLocaleLowerCase()
    .includes(query.trim().toLocaleLowerCase());
}

/** 检查荣誉是否已复制进当前简历，跨栏目去重。 */
export function hasHonor(document: ResumeDocument | null, id: string) {
  return (
    document?.sections.some(
      /* 检查所有栏目中的稳定来源标识。 */ (section) =>
        section.entries.some(
          /* 同一荣誉仅加入一次。 */ (entry) => entry.id === `honor:${id}`,
        ),
    ) ?? false
  );
}

/** 将已核对荣誉复制为普通简历条目，后续修改库资料不会改动既有简历。 */
export function addHonors(
  document: ResumeDocument,
  honors: Honor[],
  target = "",
): ResumeDocument {
  const additions: SectionEntry[] = honors
    .filter(
      /* 只采用已核对且尚未加入的条目。 */ (honor) =>
        honor.reviewed &&
        honor.status === "ready" &&
        honor.fields.name.trim() &&
        !hasHonor(document, honor.id),
    )
    .map(
      /* 将证书资料映射到现有简历字段。 */ (honor) => {
        const fields = honor.fields;
        const titledAward = fields.award && !fields.name.includes(fields.award);
        const combined = titledAward
          ? `${fields.name} · ${fields.award}`
          : fields.name;
        return {
          id: `honor:${honor.id}`,
          title: combined.length <= 300 ? combined : fields.name,
          subtitle: fields.issuer,
          period: fields.date,
          details: [
            combined.length > 300 ? fields.award : "",
            fields.level,
            fields.description,
          ]
            .filter(Boolean)
            .join("\n"),
          visible: true,
          hidden_fields: [],
          custom_fields: [],
        };
      },
    );
  if (!additions.length) return document;
  const section = target
    ? document.sections.find(
        /* 显式目标必须仍然存在。 */ (item) =>
          item.id === target && item.kind === "text",
      )
    : document.sections.find(
        /* 优先使用既有荣誉栏目。 */ (item) =>
          item.kind === "text" &&
          (item.id === "honors" || /荣誉|获奖|证书/.test(item.title)),
      );
  if (target && !section) throw new Error("目标栏目已不存在，请重新选择。");
  if (section && section.entries.length + additions.length > 100)
    throw new Error("此栏目最多容纳 100 条，请选择其他栏目。");
  if (!section && document.sections.length >= 40)
    throw new Error("栏目数量已达上限，请选择已有栏目。");
  return {
    ...document,
    sections: section
      ? document.sections.map(
          /* 保留其他栏目和当前顺序。 */ (item) =>
            item.id === section.id
              ? { ...item, entries: [...item.entries, ...additions] }
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
