import { Bookmark } from "lucide-react";
import RecruitmentSettings from "./RecruitmentSettings";
import style0 from "./recruitment.css?inline";
import RecruitmentPage from "./RecruitmentPage";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.navigation({
    slot: "recruitment",
    title: "招聘收藏夹",
    order: 60,
    icon: Bookmark,
  });
  context.style(style0);

  context.settingsPage({
    id: context.id + "/settings",
    title: "收藏",
    icon: Bookmark,
    order: 80,
    component: RecruitmentSettings,
  });
  context.component("recruitment", RecruitmentPage);
}
