import type { ComponentType, KeyboardEvent, ReactNode } from "react";
import { LoaderCircle, RefreshCw, RotateCcw } from "lucide-react";
import {
  PanelLeftIcon,
  ResumeIcon,
  ResumesIcon,
  SettingsIcon,
} from "@resume-maker/plugin-sdk/shared/components/NavigationIcon";
import ThemeSwitch from "@resume-maker/plugin-sdk/shared/components/ThemeSwitch";

export interface WorkspaceDestination {
  id: string;
  label: string;
  icon: ComponentType<{ size?: number }>;
}

interface Props {
  expanded: boolean;
  current: string;
  destinations: WorkspaceDestination[];
  pages: WorkspaceDestination[];
  children: ReactNode;
  resumeName: string;
  exporting: boolean;
  resumeLibraryOpen: boolean;
  unsaved: boolean;
  activeJobCount: number;
  onOpenResumeLibrary(): void;
  onResetLayout(): void;
  onRefresh(): void;
  onToggle(): void;
  onNavigate(id: string): void;
  onSettings(): void;
}

/** 将功能入口、当前项目、界面偏好放在同一侧栏，折叠后保留图标入口 */
export default function WorkspaceSidebar({
  expanded,
  current,
  destinations,
  pages,
  children,
  resumeName,
  exporting,
  resumeLibraryOpen,
  unsaved,
  activeJobCount,
  onOpenResumeLibrary,
  onResetLayout,
  onRefresh,
  onToggle,
  onNavigate,
  onSettings,
}: Props) {
  /** 窄屏抽屉展开时保留键盘焦点，按 Esc 返回工作区 */
  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (!expanded || !matchMedia("(max-width: 760px)").matches) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onToggle();
    }
    if (event.key !== "Tab") return;
    const buttons = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), summary, [tabindex="0"]',
      ),
    ).filter((element) => element.getClientRects().length > 0);
    const first = buttons[0];
    const last = buttons.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
  /** 统一导航名称、选中状态，保证图标模式仍可通过键盘访问 */
  function destination(item: WorkspaceDestination) {
    return (
      <button
        key={item.id}
        className={current === item.id ? "active" : ""}
        aria-current={current === item.id ? "page" : undefined}
        aria-label={item.label}
        title={!expanded ? item.label : undefined}
        onClick={() => onNavigate(item.id)}
      >
        <item.icon size={20} />
        <span className="navigation-label">{item.label}</span>
      </button>
    );
  }

  return (
    <aside
      id="workspace-sidebar"
      className={`workspace-sidebar ${expanded ? "expanded" : "collapsed"}`}
      aria-label="工作台侧边栏"
      onKeyDown={handleKeyDown}
    >
      <div className="sidebar-brand">
        <span className="brand-mark">
          <ResumeIcon size={22} />
        </span>
        <strong className="navigation-label">Resume Maker</strong>
        <button
          id={expanded ? "sidebar-collapse" : "sidebar-expand"}
          className="icon-button sidebar-toggle"
          aria-label={expanded ? "收起侧边栏" : "展开侧边栏"}
          title={expanded ? "收起侧边栏" : "展开侧边栏"}
          aria-expanded={expanded}
          aria-controls="workspace-sidebar"
          onClick={onToggle}
        >
          <PanelLeftIcon size={19} />
        </button>
      </div>
      <div className="sidebar-body">
        <nav className="area-navigation" aria-label="主要功能区">
          <span className="navigation-caption">工作空间</span>
          {destinations.map(destination)}
          {pages.length > 0 && (
            <span className="navigation-caption">更多工具</span>
          )}
          {pages.map(destination)}
        </nav>
        <div className="sidebar-projects" hidden={!expanded}>
          {children}
        </div>
      </div>
      <div className="sidebar-utilities">
        <button
          className="resume-library-trigger"
          aria-label={`当前简历：${resumeName}，管理方案和生成记录`}
          aria-haspopup="dialog"
          aria-expanded={resumeLibraryOpen}
          title={`当前简历 · ${resumeName}${unsaved ? " · 草稿已保留 · 简历方案未保存" : ""}`}
          onClick={onOpenResumeLibrary}
        >
          <ResumesIcon size={20} />
          <span className="resume-trigger-copy">
            <b>{exporting ? "正在生成简历…" : "当前简历"}</b>
            <small>{resumeName}</small>
          </span>
          {unsaved && (
            <span
              className="resume-unsaved-dot"
              aria-label="草稿已保留 · 简历方案未保存"
              title="草稿已保留 · 简历方案未保存"
            />
          )}
        </button>
        {activeJobCount > 0 && (
          <span
            className="sidebar-job-status"
            role="status"
            aria-label={`${activeJobCount} 个任务进行中`}
            title={`${activeJobCount} 个任务进行中`}
          >
            <LoaderCircle className="spin" size={14} />
            <span className="navigation-label">
              {activeJobCount} 个任务进行中
            </span>
          </span>
        )}
        <div
          className="sidebar-utility-actions"
          role="group"
          aria-label="工作台工具"
        >
          <button
            className="sidebar-settings"
            aria-label="打开设置"
            title="打开设置"
            onClick={onSettings}
          >
            <SettingsIcon size={20} />
            <span className="navigation-label">设置</span>
          </button>
          <button
            className="icon-button"
            aria-label="重置布局"
            title="重置各区域大小"
            onClick={onResetLayout}
          >
            <RotateCcw size={17} />
          </button>
          <button
            className="icon-button"
            aria-label="刷新数据"
            title="刷新数据"
            onClick={onRefresh}
          >
            <RefreshCw size={17} />
          </button>
        </div>
        <ThemeSwitch />
      </div>
    </aside>
  );
}
