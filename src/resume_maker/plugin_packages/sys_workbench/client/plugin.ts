import App from "./App";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";
import { PluginsIcon } from "@resume-maker/plugin-sdk/shared/components/NavigationIcon";
import PluginManager from "./features/plugins/PluginManager";
import css from "./features/plugins/plugin-manager.css?inline";

/** 系统工作台贡献应用外壳 */
export function activate(context: ClientContext) {
  context.component("workbench", App);
  context.style(css);
  context.settingsPage({
    id: context.id + "/plugins",
    title: "插件",
    icon: PluginsIcon,
    order: 30,
    openFor: ["plugins"],
    component: PluginManager,
  });
  context.contribute(
    "commands",
    "sys.workbench/manage-plugins",
    {
      title: "打开插件管理",
      shortcut: "Mod+Shift+m",
      /** 系统命令、外部贡献遵守相同的生命周期、快捷键规则 */
      run() {
        window.dispatchEvent(new Event("resume-plugin-manager"));
      },
    },
    0,
  );
}
