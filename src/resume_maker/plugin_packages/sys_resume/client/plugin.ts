import style6 from "./styles/privacy.css?inline";
import settingsStyle from "./styles/settings.css?inline";
import style5 from "./styles/resume-library.css?inline";
import style4 from "./styles/responsive.css?inline";
import style3 from "./styles/defaults.css?inline";
import style2 from "./styles/profile.css?inline";
import style1 from "./styles/history.css?inline";
import style0 from "./styles/workspace.css?inline";
import ResumeWorkspace from "./features/resumes/ResumeWorkspace";
import type { ClientContext } from "@resume-maker/plugin-sdk/plugins/contracts";
import ContentPreview from "./features/resumes/ContentPreview";

/** 简历系统插件负责经历和固定版本组合的业务协调 */
export function activate(context: ClientContext) {
  context.style(style0);
  context.style(style1);
  context.style(style2);
  context.style(style3);
  context.style(style4);
  context.style(style5);
  context.style(style6);
  context.style(settingsStyle);
  context.component("workspace", ResumeWorkspace);
  context.contribute("documents.previewers", "sys.resume/content", {
    title: "内容预览",
    formats: ["resume/v1"],
    component: ContentPreview,
  });
}
