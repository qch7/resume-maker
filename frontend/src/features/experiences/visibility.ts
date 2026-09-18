import type {
  Experience,
  ExperienceField,
  Meta,
  ProjectVisibility,
} from "../../shared/types/index.ts";
import { projectBodyOrder, restoreBodyOrder } from "./bodyOrder.ts";

export const META_FIELDS: ExperienceField[] = [
  "title",
  "period",
  "role",
  "stack",
  "description",
];

/** 读取当前简历的覆盖设置，未覆盖的旧版本沿用自身的显示状态。 */
export function fieldVisible(
  value: Meta,
  visibility: ProjectVisibility,
  field: ExperienceField,
) {
  return (
    visibility.fields?.[field] ?? !(value.hidden_fields ?? []).includes(field)
  );
}

/** 比较实际正文，兼容旧版本没有扩展字段以及 JSON 属性顺序不同的情况。 */
export function experienceContent(
  value?: Experience,
  settings: ProjectVisibility = {},
) {
  if (!value) return null;
  return JSON.stringify([
    ...META_FIELDS.map(/* 仅把正文纳入版本差异。 */ (field) => value[field]),
    projectBodyOrder(value, settings),
    (value.custom_fields ?? []).map(
      /* 显隐属于简历，名称、值及顺序属于内容。 */ (field) => [
        field.id,
        field.label,
        field.value,
      ],
    ),
    value.highlights.map(
      /* 显式列出字段，避免接口补全默认值导致误判。 */ (point) => [
        point.id,
        point.title,
        point.text,
        point.evidence ?? [],
      ],
    ),
  ]);
}

/** 从旧元信息草稿分离显隐，内容改动保留在原草稿，旧版本从不被改写。 */
export function separateMetaVisibility(
  base: Experience,
  meta: Meta,
  settings: ProjectVisibility = {},
) {
  const visibility: ProjectVisibility = { fields: {}, custom_fields: {} };
  const hidden = meta.hidden_fields ?? base.hidden_fields ?? [];
  for (const field of META_FIELDS) {
    if (hidden.includes(field) !== (base.hidden_fields ?? []).includes(field))
      visibility.fields![field] = !hidden.includes(field);
  }
  const custom = (meta.custom_fields ?? base.custom_fields ?? []).map(
    /* 新条目仍保留名称和内容，只把隐藏状态移出版本。 */ (field) => {
      const original = base.custom_fields?.find(
        /* 按稳定标识对照。 */ (item) => item.id === field.id,
      );
      const visible = original?.visible ?? true;
      if (field.visible !== visible)
        visibility.custom_fields![field.id] = field.visible;
      return { ...field, visible };
    },
  );
  const migrated =
    Object.keys(visibility.fields!).length +
      Object.keys(visibility.custom_fields!).length >
    0;
  const content = {
    ...base,
    ...meta,
    highlights: base.highlights,
    hidden_fields: base.hidden_fields ?? [],
    custom_fields: custom,
  };
  const { highlights: _highlights, ...normalized } = content;
  const restored = restoreBodyOrder(normalized, base, settings);
  return {
    visibility,
    migrated,
    meta: restored,
    normalizedOrder:
      JSON.stringify(restored.body_order ?? null) !==
      JSON.stringify(meta.body_order ?? null),
    contentChanged:
      experienceContent(content, settings) !==
      experienceContent(base, settings),
  };
}
