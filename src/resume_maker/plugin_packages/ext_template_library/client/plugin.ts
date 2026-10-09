import TemplatePicker from "./TemplatePicker";
import css from "./template-library.css?inline";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";

/** 模板库拥有选择弹窗、组织操作和样式，停用时撤销插槽 */
export function activate(context: ClientContext) {
  context.style(css);
  context.component("templatePicker", TemplatePicker);
}
