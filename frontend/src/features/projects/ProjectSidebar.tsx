import {
  ArrowDownAZ,
  ArrowUpAZ,
  Bell,
  ChevronDown,
  ChevronRight,
  FolderPlus,
  LoaderCircle,
  MoreHorizontal,
  Plus,
} from "lucide-react";
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { loadLocal } from "../../shared/lib/storage";
import type {
  Conversation,
  Job,
  Project,
  ResumeItem,
} from "../../shared/types";
import { restoreSidebarSort, sortSidebar } from "./sort";

interface Props {
  projects: Project[];
  conversations: Conversation[];
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
  projects,
  conversations,
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
  const [sidebarSort, setSidebarSort] = useState(
    /* 仅在首次挂载时读取缓存或计算初始状态。 */ () =>
      restoreSidebarSort(loadLocal("rm.sidebarSort", "recent")),
  );
  const sortedSidebar = sortSidebar(projects, conversations, sidebarSort);
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      localStorage.setItem("rm.sidebarSort", JSON.stringify(sidebarSort));
    },
    [sidebarSort],
  );
  return (
    <aside className="sidebar">
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
              setSidebarSort("recent")
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
              setSidebarSort(sidebarSort === "asc" ? "desc" : "asc")
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
        {sortedSidebar.projects.map(
          /* 按稳定标识生成对应的列表条目。 */ (p) => (
            <section className="project-group" key={p.id}>
              <div
                className={`project-row ${activeProject === p.id && mode === "edit" ? "selected" : ""}`}
              >
                <input
                  type="checkbox"
                  aria-label={`将 ${p.name} 加入简历`}
                  checked={items.some(
                    /* 检查条目是否满足当前选择或校验条件。 */ (i) =>
                      i.project_id === p.id,
                  )}
                  onChange={
                    /* 把控件的新值同步到对应编辑状态。 */ () =>
                      onToggleProject(p.id)
                  }
                />
                <button
                  className="project-name"
                  title={p.name}
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      onNavigate(p.id)
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
                  aria-label={`${folded[p.id] ? "展开" : "收起"} ${p.name} 会话`}
                  aria-expanded={!folded[p.id]}
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      setFolded(
                        /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                          v,
                        ) => ({ ...v, [p.id]: !v[p.id] }),
                      )
                  }
                >
                  {folded[p.id] ? (
                    <ChevronRight size={14} />
                  ) : (
                    <ChevronDown size={14} />
                  )}
                </button>
              </div>
              {!folded[p.id] && (
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
              )}
            </section>
          ),
        )}
      </nav>
      <button className="sidebar-footer" onClick={onImport}>
        <FolderPlus size={17} />
        导入项目
      </button>
    </aside>
  );
}
