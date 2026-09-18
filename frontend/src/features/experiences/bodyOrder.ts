import type {
  Meta,
  ProjectBodyKey,
  ProjectVisibility,
} from "../../shared/types/index.ts";

/** 标题与时间固定在顶部，优先使用版本顺序，旧版本兼容原简历设置。 */
export function projectBodyOrder(
  value: Meta,
  settings: ProjectVisibility,
): ProjectBodyKey[] {
  const defaults: ProjectBodyKey[] = [
    "role",
    "stack",
    "description",
    "highlights",
    ...(value.custom_fields ?? []).map(
      /* 自定义信息用稳定标识排序，改名不改变位置。 */ (
        field,
      ): ProjectBodyKey => `custom:${field.id}`,
    ),
  ];
  const available = new Set(defaults);
  return [
    ...new Set([...(value.body_order ?? settings.order ?? []), ...defaults]),
  ].filter(
    /* 删除和切换版本后忽略不存在的条目，但不修改保存的其他版本位置。 */ (
      key,
    ) => available.has(key),
  );
}

/** 排回基线位置时恢复其原始表示，兼容旧版本借用简历排序及省略的默认字段。 */
export function restoreBodyOrder(
  value: Meta,
  base: Meta,
  settings: ProjectVisibility,
): Meta {
  const original = { ...value, body_order: base.body_order ?? null };
  return JSON.stringify(projectBodyOrder(value, settings)) ===
    JSON.stringify(projectBodyOrder(original, settings))
    ? original
    : value;
}
