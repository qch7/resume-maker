import { FileScan } from "lucide-react";
import style0 from "./templates.css?inline";
import TemplateAdapter from "./TemplateAdapter";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.navigation({
    slot: "templates",
    title: "Word 模板",
    order: 50,
    icon: FileScan,
  });
  context.style(style0);

  context.component("templates", TemplateAdapter);
}
