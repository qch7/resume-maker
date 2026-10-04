import ConversationSettings from "./ConversationSettings";
import Chat from "./Chat";
import type { ClientContext } from "../../plugins/contracts";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.settingsPage({
    id: context.id + "/history",
    title: "会话归档",
    order: 15,
    component: ConversationSettings,
  });
  context.component("conversation", Chat);
}
