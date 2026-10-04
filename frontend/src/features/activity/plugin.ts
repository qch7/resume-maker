import style0 from "../../styles/activity.css?inline";
import Activity from "./Activity";
import type { ClientContext } from "../../plugins/contracts";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.style(style0);

  context.component("activity", Activity);
}
