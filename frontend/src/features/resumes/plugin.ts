import ResumeWorkspace from "./ResumeWorkspace";
import type { ClientContext } from "../../plugins/contracts";

/** 简历系统插件负责经历和固定版本组合的业务协调 */
export function activate(context: ClientContext) {
  context.component("workspace", ResumeWorkspace);
}
