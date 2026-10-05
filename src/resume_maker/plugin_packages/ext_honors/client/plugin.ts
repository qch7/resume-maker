import { Award } from "lucide-react";
import style0 from "./honors.css?inline";
import HonorLibrary from "./HonorLibrary";
import HonorEditor from "./HonorEditor";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";

/** 注册插件拥有的客户端插槽，停用时由实例作用域撤销 */
export function activate(context: ClientContext) {
  context.navigation({
    slot: "honors",
    title: "荣誉证书",
    order: 40,
    icon: Award,
  });
  context.style(style0);

  context.component("honors", HonorLibrary);
  context.component("honorEditor", HonorEditor);
}
