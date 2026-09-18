import type {
  CustomInfoField,
  ResumeSection,
  SectionEntry,
  SectionEntryField,
} from "../../shared/types/index.ts";
import { emptyHonor, HONOR_FIELDS, type HonorFields } from "./fields.ts";

const ENTRY_FIELDS: Partial<Record<keyof HonorFields, SectionEntryField>> = {
  name: "title",
  issuer: "subtitle",
  date: "period",
  description: "details",
};

/** 依据栏目用途选择荣誉录入表单，不依赖 Word 模板。 */
export function isHonorSection(section: ResumeSection) {
  return (
    section.kind === "text" &&
    (section.id === "honors" || /荣誉|获奖|证书/.test(section.title))
  );
}

/** 稳定来源标识保证荣誉移到其他栏目或栏目改名后仍保留字段语义。 */
export function isHonorEntry(entry: SectionEntry, section: ResumeSection) {
  return entry.id.startsWith("honor:") || isHonorSection(section);
}

/** 固定荣誉信息使用独立标识；用户自行添加的信息仍可命名和删除。 */
export function isHonorCustomField(field: CustomInfoField) {
  return HONOR_FIELDS.some(
    /* 仅匹配本功能拥有的固定字段，不根据用户标签猜测。 */ (item) =>
      !ENTRY_FIELDS[item.key] && field.id === `honor-field:${item.key}`,
  );
}

/** 读取同名荣誉资料，固定文本与可选信息各自只有一个保存位置。 */
export function honorFieldValue(entry: SectionEntry, key: keyof HonorFields) {
  const field = ENTRY_FIELDS[key];
  return field
    ? entry[field]
    : (entry.custom_fields.find(
        /* 根据固定标识读取可选信息。 */ (item) =>
          item.id === `honor-field:${key}`,
      )?.value ?? "");
}

/** 统一表单保存时只提取荣誉正文，排除各份简历的显隐与自定义备注。 */
export function honorFieldsFromEntry(entry: SectionEntry): HonorFields {
  const fields = emptyHonor();
  for (const field of HONOR_FIELDS) {
    const value = honorFieldValue(entry, field.key);
    if (field.key === "category") {
      if (value) fields.category = value as HonorFields["category"];
    } else fields[field.key] = value;
  }
  return fields;
}

/** 打开统一编辑表单时使用最新库资料，同时保留当前简历未保存的显示设置。 */
export function entryWithHonorFields(entry: SectionEntry, fields: HonorFields) {
  for (const field of HONOR_FIELDS)
    entry = updateHonorField(entry, field.key, { value: fields[field.key] });
  return entry;
}

/** 读取简历显隐；尚未填写的可选荣誉信息默认隐藏。 */
export function honorFieldHidden(entry: SectionEntry, key: keyof HonorFields) {
  const field = ENTRY_FIELDS[key];
  return field
    ? entry.hidden_fields.includes(field)
    : !entry.custom_fields.find(
        /* 保留用户已经保存的显示选择。 */ (item) =>
          item.id === `honor-field:${key}`,
      )?.visible;
}

/** 单独修改荣誉字段或显隐，保留同条记录的其他内容和自定义信息。 */
export function updateHonorField(
  entry: SectionEntry,
  key: keyof HonorFields,
  change: { value?: string; hidden?: boolean },
): SectionEntry {
  const field = ENTRY_FIELDS[key];
  if (field) {
    const updated = { ...entry };
    if (change.value !== undefined) updated[field] = change.value;
    if (change.hidden !== undefined)
      updated.hidden_fields = [
        ...entry.hidden_fields.filter(
          /* 先移除本字段以避免重复标识。 */ (item) => item !== field,
        ),
        ...(change.hidden ? [field] : []),
      ];
    return updated;
  }
  const definition = HONOR_FIELDS.find(
    /* 由同一份字段定义提供标签。 */ (item) => item.key === key,
  )!;
  const id = `honor-field:${key}`;
  const existing = entry.custom_fields.find(
    /* 已有值和显隐独立保留。 */ (item) => item.id === id,
  );
  if (!existing && entry.custom_fields.length >= 25)
    throw new Error("此条资料的信息项已满，请先删除不需要的自定义信息。");
  const updated = {
    id,
    label:
      entry.field_definitions?.find(
        /* 简历字段名称独立于荣誉库的识别字段。 */ (item) => item.id === id,
      )?.label ?? definition.label,
    value: change.value ?? existing?.value ?? "",
    visible:
      change.hidden === undefined
        ? (existing?.visible ?? false)
        : !change.hidden,
  };
  return {
    ...entry,
    custom_fields: existing
      ? entry.custom_fields.map(
          /* 只更新当前字段，不改变其顺序。 */ (item) =>
            item.id === id ? updated : item,
        )
      : [...entry.custom_fields, updated],
  };
}

/** 只显示证书名和日期，资料值及整条记录的显隐保持不变。 */
export function nameAndDateOnly(entry: SectionEntry): SectionEntry {
  return {
    ...entry,
    hidden_fields: ["subtitle", "details"],
    custom_fields: entry.custom_fields.map(
      /* 收起所有附加信息，之后可逐项恢复。 */ (field) => ({
        ...field,
        visible: false,
      }),
    ),
  };
}

/** 复制完整荣誉资料，默认仅证书名称和获得日期参与简历排版。 */
export function newHonorEntry(
  fields: HonorFields = emptyHonor(),
  id = `honor:manual:${crypto.randomUUID()}`,
): SectionEntry {
  let entry: SectionEntry = {
    id,
    title: "",
    subtitle: "",
    period: "",
    details: "",
    visible: true,
    hidden_fields: [],
    custom_fields: [],
  };
  for (const field of HONOR_FIELDS)
    entry = updateHonorField(entry, field.key, { value: fields[field.key] });
  return nameAndDateOnly(entry);
}
