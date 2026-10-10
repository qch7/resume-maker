import TemplatePreview from "./TemplatePreview";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";

/** Word 插件拥有精确分页预览，系统内容预览仍可独立使用 */
export function activate(context: ClientContext) {
  context.contribute("documents.previewers", "ext.word/pages", {
    title: "Word 精确分页",
    formats: ["resume/v1"],
    component: TemplatePreview,
  });
}
