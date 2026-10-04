import style1 from "../../styles/template-library.css?inline";
import style0 from "../../styles/templates.css?inline";
import TemplateAdapter from "./TemplateAdapter";
import type { ClientContext } from "../../plugins/contracts";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.style(style0);
  context.style(style1);

  context.component("templates", TemplateAdapter);
}
