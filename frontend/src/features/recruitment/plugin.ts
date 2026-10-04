import RecruitmentSettings from "../settings/RecruitmentSettings";
import style0 from "../../styles/recruitment.css?inline";
import RecruitmentPage from "./RecruitmentPage";
import type { ClientContext } from "../../plugins/contracts";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.style(style0);

  context.settingsPage({
    id: context.id + "/settings",
    title: "招聘收藏夹",
    order: 30,
    component: RecruitmentSettings,
  });
  context.component("recruitment", RecruitmentPage);
}
