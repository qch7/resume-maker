import App from "./App";
import type { ClientContext } from "../plugins/contracts";

/** 系统工作台贡献应用外壳 */
export function activate(context: ClientContext) {
  context.component("workbench", App);
  context.contribute(
    "commands",
    "sys.workbench/manage-plugins",
    {
      title: "打开插件管理",
      shortcut: "Mod+Shift+m",
      /** 系统命令和外部贡献遵守相同的生命周期和快捷键规则 */
      run() {
        window.dispatchEvent(new Event("resume-plugin-manager"));
      },
    },
    0,
  );
}
