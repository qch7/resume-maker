import ConversationSettings from "./ConversationSettings";
import Chat from "./Chat";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";
import { ArchiveIcon } from "@resume-maker/plugin-sdk/shared/components/NavigationIcon";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.settingsPage({
    id: context.id + "/history",
    title: "归档",
    icon: ArchiveIcon,
    order: 70,
    component: ConversationSettings,
  });
  context.component("conversation", Chat);
}
