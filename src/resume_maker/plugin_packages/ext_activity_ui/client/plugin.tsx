import css from "./activity.css?inline";
import { Activity as ActivityIcon } from "lucide-react";
import Activity from "./Activity";
import type {
  ClientContext,
  WorkbenchPageProps,
} from "@resume-maker/plugin-sdk/plugins/contracts";
import { useActivityPreferences } from "@resume-maker/plugin-sdk/shared/hooks/useActivityPreferences";

/** 日志页面持有自身显示状态，设置变化从宿主公开状态同步 */
function ActivityPage({ openSettings, settingsVersion }: WorkbenchPageProps) {
  const preferences = useActivityPreferences();
  return (
    <Activity
      preferencesState={preferences}
      refreshVersion={settingsVersion}
      onOpenSettings={() => openSettings("activity")}
    />
  );
}

/** 注册通用工作台页面及样式，卸载由插件作用域撤销 */
export function activate(context: ClientContext) {
  context.style(css);
  context.workbenchPage({
    id: context.id + "/main",
    title: "系统日志",
    order: 70,
    icon: ActivityIcon,
    component: ActivityPage,
  });
}
