import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";
import ProviderSettingsPanel from "./ProviderSettings";
import { Cpu } from "lucide-react";

/** 供应商独立贡献设置，不要求修改系统设置页 */
export function activate(context: ClientContext) {
  context.settingsPage({
    id: context.id + "/connection",
    title: "模型",
    icon: Cpu,
    order: 20,
    component: ProviderSettingsPanel,
  });
}
