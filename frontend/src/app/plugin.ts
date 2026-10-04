import App from "./App";
import type { ClientContext } from "../plugins/contracts";

/** 系统工作台贡献应用外壳 */
export function activate(context: ClientContext) {
  context.component("workbench", App);
}
