import style0 from "../../styles/honors.css?inline";
import HonorLibrary from "./HonorLibrary";
import HonorEditor from "./HonorEditor";
import type { ClientContext } from "../../plugins/contracts";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.style(style0);

  context.component("honors", HonorLibrary);
  context.component("honorEditor", HonorEditor);
}
