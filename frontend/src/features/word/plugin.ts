import TemplatePreview from "../resumes/TemplatePreview";
import type { ClientContext } from "../../plugins/contracts";

/** Word 插件拥有精确分页预览，系统内容预览仍可独立使用 */
export function activate(context: ClientContext) {
  context.component("wordPreview", TemplatePreview);
}
