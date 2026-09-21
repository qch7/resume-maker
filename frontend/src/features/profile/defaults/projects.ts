import type {
  DefaultField,
  Meta,
  ProjectVisibility,
} from "../../../shared/types/index.ts";
import { applyCustomDefaults } from "./model.ts";

/** 为项目表单补齐默认项和初始显示设置 */
export function projectDefaultView(
  original: Meta,
  settings: ProjectVisibility,
  definitions?: DefaultField[] | null,
) {
  if (!definitions) return { value: original, visibility: settings, error: "" };
  const visibility: ProjectVisibility = {
    ...settings,
    fields: {},
    custom_fields: {},
  };
  for (const field of definitions) {
    if (field.id.startsWith("default:"))
      visibility.custom_fields![field.id] = field.visible;
    else if (
      ["title", "period", "role", "stack", "description"].includes(field.id)
    )
      visibility.fields![
        field.id as keyof NonNullable<ProjectVisibility["fields"]>
      ] =
        field.visible &&
        !(original.hidden_fields ?? []).includes(
          field.id as keyof NonNullable<ProjectVisibility["fields"]>,
        );
  }
  Object.assign(visibility.fields!, settings.fields);
  Object.assign(visibility.custom_fields!, settings.custom_fields);
  try {
    return {
      value: {
        ...original,
        custom_fields: applyCustomDefaults(
          original.custom_fields ?? [],
          definitions,
        ),
      },
      visibility,
      error: "",
    };
  } catch (failure) {
    return {
      value: original,
      visibility,
      error: failure instanceof Error ? failure.message : String(failure),
    };
  }
}
