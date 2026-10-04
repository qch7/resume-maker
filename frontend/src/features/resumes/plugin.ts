import ResumeWorkspace from "./ResumeWorkspace";
import type { ClientContext } from "../../plugins/contracts";
import ContentPreview from "./ContentPreview";

/** 简历系统插件负责经历和固定版本组合的业务协调 */
export function activate(context: ClientContext) {
  context.component("workspace", ResumeWorkspace);
  context.contribute("documents.previewers", "sys.resume/content", {
    title: "内容预览",
    formats: ["resume/v1"],
    component: ContentPreview,
  });
}
