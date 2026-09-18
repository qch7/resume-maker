import type {
  Experience,
  ExperienceField,
  Meta,
  ProjectVisibility,
} from "../../shared/types/index.ts";
import { projectBodyOrder } from "./bodyOrder.ts";

export const META_FIELDS: ExperienceField[] = [
  "title",
  "period",
  "role",
  "stack",
  "description",
];

/** 读取当前简历的覆盖设置；未覆盖的旧版本沿用自身的显示状态 */
export function fieldVisible(
  value: Meta,
  visibility: ProjectVisibility,
  field: ExperienceField,
) {
  return (
    visibility.fields?.[field] ?? !(value.hidden_fields ?? []).includes(field)
  );
}

/** 比较实际正文；兼容旧版本没有扩展字段以及 JSON 属性顺序不同的情况 */
export function experienceContent(
  value?: Experience,
  settings: ProjectVisibility = {},
) {
  if (!value) return null;
  return JSON.stringify([
    ...META_FIELDS.map(/* 仅把正文纳入版本差异 */ (field) => value[field]),
    projectBodyOrder(value, settings),
    (value.custom_fields ?? []).map(
      /* 显隐属于简历；名称、值及顺序属于内容 */ (field) => [
        field.id,
        field.label,
        field.value,
      ],
    ),
    value.highlights.map(
      /* 显式列出字段以免接口补全默认值导致误判 */ (point) => [
        point.id,
        point.title,
        point.text,
        point.evidence ?? [],
      ],
    ),
  ]);
}
