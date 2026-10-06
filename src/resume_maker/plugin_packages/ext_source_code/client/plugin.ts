import SourceSettings from "./SourceSettings";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";

/** 来源扫描设置归属源码插件，关闭后不保留隐藏扫描状态 */
export function activate(context: ClientContext) {
  context.settingsPage({
    id: context.id + "/import",
    title: "扫描导入",
    order: 5,
    component: SourceSettings,
    openFor: ["projects"],
    group: "projects",
  });
}
