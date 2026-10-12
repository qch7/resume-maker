import type { CSSProperties } from "react";
import activity from "../../assets/icons/navigation/activity.svg?url";
import archive from "../../assets/icons/navigation/archive.svg?url";
import backup from "../../assets/icons/navigation/backup.svg?url";
import chat from "../../assets/icons/navigation/chat.svg?url";
import edit from "../../assets/icons/navigation/edit.svg?url";
import honors from "../../assets/icons/navigation/honors.svg?url";
import model from "../../assets/icons/navigation/model.svg?url";
import panelLeft from "../../assets/icons/navigation/panel-left.svg?url";
import plugins from "../../assets/icons/navigation/plugins.svg?url";
import privacy from "../../assets/icons/navigation/privacy.svg?url";
import profile from "../../assets/icons/navigation/profile.svg?url";
import projects from "../../assets/icons/navigation/projects.svg?url";
import recruitment from "../../assets/icons/navigation/recruitment.svg?url";
import resume from "../../assets/icons/navigation/resume.svg?url";
import resumes from "../../assets/icons/navigation/resumes.svg?url";
import sections from "../../assets/icons/navigation/sections.svg?url";
import settings from "../../assets/icons/navigation/settings.svg?url";
import templates from "../../assets/icons/navigation/templates.svg?url";

const sources = {
  activity,
  archive,
  backup,
  chat,
  edit,
  honors,
  model,
  "panel-left": panelLeft,
  plugins,
  privacy,
  profile,
  projects,
  recruitment,
  resume,
  resumes,
  sections,
  settings,
  templates,
};

export type NavigationIconName = keyof typeof sources;

export interface NavigationGlyphProps {
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export interface NavigationIconProps extends NavigationGlyphProps {
  name: NavigationIconName;
}

/** 将导航资源渲染为装饰图标，颜色继承当前文字，尺寸单位为像素 */
export default function NavigationIcon({
  name,
  size = 20,
  className,
  style,
}: NavigationIconProps) {
  const mask = `url("${sources[name]}") center / contain no-repeat`;
  return (
    <span
      aria-hidden="true"
      className={["navigation-icon", className].filter(Boolean).join(" ")}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        flexShrink: 0,
        verticalAlign: "middle",
        backgroundColor: "currentColor",
        mask,
        WebkitMask: mask,
        ...style,
      }}
    />
  );
}

/** 将固定图标名称适配为导航贡献所需的组件 */
function createNavigationIcon(name: NavigationIconName) {
  /** 使用共享资源渲染指定导航图标 */
  function NavigationGlyph(props: NavigationGlyphProps) {
    return <NavigationIcon name={name} {...props} />;
  }
  return NavigationGlyph;
}

export { NavigationIcon };
export const ActivityIcon = createNavigationIcon("activity");
export const ArchiveIcon = createNavigationIcon("archive");
export const BackupIcon = createNavigationIcon("backup");
export const ChatIcon = createNavigationIcon("chat");
export const EditIcon = createNavigationIcon("edit");
export const HonorsIcon = createNavigationIcon("honors");
export const ModelIcon = createNavigationIcon("model");
export const PanelLeftIcon = createNavigationIcon("panel-left");
export const PluginsIcon = createNavigationIcon("plugins");
export const PrivacyIcon = createNavigationIcon("privacy");
export const ProfileIcon = createNavigationIcon("profile");
export const ProjectsIcon = createNavigationIcon("projects");
export const RecruitmentIcon = createNavigationIcon("recruitment");
export const ResumeIcon = createNavigationIcon("resume");
export const ResumesIcon = createNavigationIcon("resumes");
export const SectionsIcon = createNavigationIcon("sections");
export const SettingsIcon = createNavigationIcon("settings");
export const TemplatesIcon = createNavigationIcon("templates");
