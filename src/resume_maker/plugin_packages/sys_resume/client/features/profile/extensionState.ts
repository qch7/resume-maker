import type { ResumeDocument } from "@resume-maker/plugin-sdk/shared/types/index";
import {
  jsonCopy,
  type JsonValue,
} from "@resume-maker/plugin-sdk/plugins/extensions";

/** 扩展资料只更新所属命名空间，普通字段和缺失插件的资料保持原样 */
export function updateExtension(
  value: ResumeDocument,
  owner: string,
  next: JsonValue,
): ResumeDocument {
  if (!/^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$/.test(owner))
    throw new Error("扩展资料须使用插件命名空间。");
  return {
    ...value,
    extensions: jsonCopy({ ...value.extensions, [owner]: next }),
  };
}
