import {
  ArrowDownAZ,
  ArrowUpAZ,
  Bell,
  ChevronDown,
  ChevronRight,
  FolderPlus,
  LoaderCircle,
  MoreHorizontal,
  PanelLeftClose,
  Plus,
} from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import type { Job, Project, ResumeItem } from "../../shared/types";
import type { SidebarSort, sortSidebar } from "./sort";

interface Props {
  onCollapse: () => void;
  sortedSidebar: ReturnType<typeof sortSidebar>;
  sidebarSort: SidebarSort;
  onSortChange: (sort: SidebarSort) => void;
  activeJobs: Job[];
  items: ResumeItem[];
  activeProject: string;
  conversationId: string;
  mode: "edit" | "chat";
  creatingConversation: string;
  folded: Record<string, boolean>;
  setFolded: Dispatch<SetStateAction<Record<string, boolean>>>;
  onNavigate: (projectId: string, conversationId?: string) => void;
  onToggleProject: (projectId: string) => void;
  onNewConversation: (projectId: string) => void;
  onArchive: (projectId: string, conversationId: string) => void;
  onImport: () => void;
}

/** 展示和排序项目及会话，通过回调把导航与写入交给工作台协调。 */
export default function ProjectSidebar({
  onCollapse,
  sortedSidebar,
  sidebarSort,
  onSortChange,
  activeJobs,
  items,
  activeProject,
  conversationId,
  mode,
  creatingConversation,
  folded,
  setFolded,
  onNavigate,
  onToggleProject,
  onNewConversation,
  onArchive,
  onImport,
}: Props) {
  /** 按来源分组递归显示项目；整体与子项目分别持有选择状态和会话。 */
  function renderProject(p: Project) {
    const children = sortedSidebar.projects.filter(
      /* 子项目始终留在所属整体项目下，组内沿用当前排序。 */ (child) =>
        child.parent_id === p.id,
    );
    const collapsed = folded[p.id] ?? !!p.parent_id;
    return (
      <section
        className={`project-group${p.parent_id ? " subproject-group" : ""}`}
        key={p.id}
      >
        <div
          className={`project-row ${activeProject === p.id && mode === "edit" ? "selected" : ""}`}
        >
          <input
            type="checkbox"
            aria-label={`将 ${p.name} 加入简历`}
            title={
              children.length
                ? "勾选整体经历；子项目可分别勾选"
                : "将该项目单独加入简历"
            }
            checked={items.some(
              /* 检查条目是否满足当前选择或校验条件。 */ (i) =>
                i.project_id === p.id,
            )}
            onChange={
              /* 把控件的新值同步到对应编辑状态。 */ () => onToggleProject(p.id)
            }
          />
          <button
            className="project-name"
            title={p.parent_id ? `${p.name}\n${p.roots.join("\n")}` : p.name}
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () => onNavigate(p.id)
            }
          >
            {p.name}
          </button>
          <button
            className="icon-button"
            aria-label={`为 ${p.name} 新建会话`}
            title={`为 ${p.name} 新建会话`}
            disabled={!!creatingConversation}
            aria-busy={creatingConversation === p.id}
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                onNewConversation(p.id)
            }
          >
            {creatingConversation === p.id ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <Plus size={15} />
            )}
          </button>
          <button
            className="icon-button"
            aria-label={`${collapsed ? "展开" : "收起"} ${p.name} ${children.length ? "子项目与会话" : "会话"}`}
            aria-expanded={!collapsed}
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                setFolded(
                  /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                    v,
                  ) => ({ ...v, [p.id]: !collapsed }),
                )
            }
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
        {!collapsed && (
          <>
            {children.length > 0 && (
              <div className="project-scope-label">整体对话</div>
            )}
            <div className="session-list">
              {sortedSidebar.conversations
                .filter(
                  /* 保留满足当前范围或有效性条件的条目。 */ (c) =>
                    c.project_id === p.id,
                )
                .map(
                  /* 按稳定标识生成对应的列表条目。 */ (c) => (
                    <div
                      className={`session-row ${c.id === conversationId && activeProject === p.id && mode === "chat" ? "selected" : ""}`}
                      key={c.id}
                    >
                      <button
                        className="session-button"
                        aria-current={
                          c.id === conversationId &&
                          activeProject === p.id &&
                          mode === "chat"
                            ? "page"
                            : undefined
                        }
                        onClick={
                          /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                            onNavigate(p.id, c.id)
                        }
                      >
                        {c.title}
                        {activeJobs.some(
                          /* 检查条目是否满足当前选择或校验条件。 */ (j) =>
                            j.conversation_id === c.id,
                        ) && <span className="activity-dot" />}
                      </button>
                      <details className="session-menu">
                        <summary aria-label={`管理会话 ${c.title}`}>
                          <MoreHorizontal size={15} />
                        </summary>
                        <div>
                          <button
                            onClick={
                              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                                onArchive(p.id, c.id)
                            }
                          >
                            归档会话
                          </button>
                        </div>
                      </details>
                    </div>
                  ),
                )}
            </div>
            {children.length > 0 && (
              <div className="subproject-list">
                <div className="project-scope-label">
                  子项目 · {children.length}
                </div>
                {children.map(renderProject)}
              </div>
            )}
          </>
        )}
      </section>
    );
  }
  return (
    <aside id="project-sidebar" className="sidebar" aria-label="项目库">
      <div className="sidebar-heading">
        <span>
          项目库
          <span className="count-badge">{sortedSidebar.projects.length}</span>
        </span>
        <button
          id="sidebar-collapse"
          className="icon-button"
          aria-label="收起项目库"
          title="收起项目库"
          aria-expanded={true}
          aria-controls="project-sidebar"
          onClick={onCollapse}
        >
          <PanelLeftClose size={17} />
        </button>
      </div>
      <div className="sidebar-sort" role="group" aria-label="项目与会话排序">
        <span>
          {sidebarSort === "recent"
            ? "最近修改"
            : sidebarSort === "asc"
              ? "A → Z"
              : "Z → A"}
        </span>
        <button
          className="icon-button"
          aria-label="按最近修改排序"
          aria-pressed={sidebarSort === "recent"}
          title="最近修改的项目与会话在最上面"
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
              onSortChange("recent")
          }
        >
          <Bell size={16} />
        </button>
        <button
          className="icon-button"
          aria-label={
            sidebarSort === "asc" ? "按字母倒序排序" : "按字母正序排序"
          }
          aria-pressed={sidebarSort !== "recent"}
          title={
            sidebarSort === "asc"
              ? "当前 A → Z，点击切换 Z → A"
              : sidebarSort === "desc"
                ? "当前 Z → A，点击切换 A → Z"
                : "按字母 A → Z 排序，再次点击倒序"
          }
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
              onSortChange(sidebarSort === "asc" ? "desc" : "asc")
          }
        >
          {sidebarSort === "desc" ? (
            <ArrowUpAZ size={17} />
          ) : (
            <ArrowDownAZ size={17} />
          )}
        </button>
      </div>
      <nav className="project-navigation" aria-label="项目与会话">
        {sortedSidebar.rootProjects.map(renderProject)}
      </nav>
      <button className="sidebar-footer" onClick={onImport}>
        <FolderPlus size={17} />
        导入项目
      </button>
    </aside>
  );
}
