import {
  FolderPlus,
  LoaderCircle,
  PanelLeftClose,
  RefreshCw,
  RotateCcw,
  Settings as SettingsIcon,
  Sparkles,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import Chat from "../features/conversations/Chat";
import Editor from "../features/experiences/Editor";
import { clearLocalDrafts } from "../features/experiences/useField";
import ProjectSidebar from "../features/projects/ProjectSidebar";
import Composer from "../features/resumes/Composer";
import {
  NEW_RESUME,
  useResumeComposition,
} from "../features/resumes/useResumeComposition";
import Settings from "../features/settings/Settings";
import { getWorkflow, type GuideTarget } from "../features/workflow/state";
import Workflow from "../features/workflow/Workflow";
import ResizeHandle from "../shared/components/ResizeHandle";
import ThemeSwitch from "../shared/components/ThemeSwitch";
import { useRemote } from "../shared/hooks/useRemote";
import { api } from "../shared/lib/api";
import { flushDrafts } from "../shared/lib/draftRegistry";
import { clamp, DEFAULT_LAYOUT } from "../shared/lib/layout";
import { loadLocal } from "../shared/lib/storage";
import type {
  Conversation,
  ConversationDetail,
  ProjectDetail,
  Proposal,
  Resume,
  Revision,
  State,
} from "../shared/types/index";
import { useWorkspaceLayout } from "./useWorkspaceLayout";

const EMPTY: State = {
  projects: [],
  conversations: [],
  resumes: [],
  templates: [],
  jobs: [],
};
/** 组装工作台，并协调项目导航、经历发布、会话和简历组合之间的状态。 */
export default function App() {
  const {
    sidebar,
    setSidebar,
    layout,
    setLayout,
    previewFocused,
    setPreviewFocused,
    workbench,
    columns,
    guideMin,
    guideMax,
    resize,
  } = useWorkspaceLayout();
  const [state, setState] = useState<State>(EMPTY),
    [loaded, setLoaded] = useState(false);
  const [activeProject, setActiveProject] = useState("");
  const [selectedRevisions, setSelectedRevisions] = useState<
    Record<string, string>
  >({});
  const [selectedConversations, setSelectedConversations] = useState<
    Record<string, string>
  >({});
  const [creatingConversation, setCreatingConversation] = useState("");
  const conversationCreationPending = useRef(false);
  const [mode, setMode] = useState<"edit" | "chat">("edit");
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  const [edited, setEdited] = useState<Record<string, boolean>>({});
  const [guideTarget, setGuideTarget] = useState<GuideTarget | null>(null);
  const [modal, setModal] = useState<
    "projects" | "templates" | "settings" | null
  >(null);
  const [refresh, setRefresh] = useState(0),
    [toast, setToast] = useState<{ text: string; error?: boolean } | null>(
      null,
    );
  const [revisionCache, setRevisionCache] = useState<Record<string, Revision>>(
    {},
  );
  const initialized = useRef(false),
    navigation = useRef(0);
  const project = state.projects.find(
    /* 定位与当前标识或条件匹配的条目。 */ (p) => p.id === activeProject,
  );
  const revisionId =
    selectedRevisions[activeProject] ?? project?.head_revision ?? "";
  const conversationId =
    selectedConversations[activeProject] ??
    state.conversations.find(
      /* 定位与当前标识或条件匹配的条目。 */ (c) =>
        c.project_id === activeProject,
    )?.id ??
    "";
  const activeJobs = state.jobs.filter(
    /* 保留满足当前范围或有效性条件的条目。 */ (j) =>
      ["running", "queued"].includes(j.status),
  );
  const currentJob = activeJobs.find(
    /* 定位与当前标识或条件匹配的条目。 */ (j) =>
      j.conversation_id === conversationId,
  );
  const statusKey = state.jobs
    .filter(
      /* 保留满足当前范围或有效性条件的条目。 */ (j) =>
        j.conversation_id === conversationId,
    )
    .map(
      /* 逐项转换数据，保留当前业务需要的字段。 */ (j) => `${j.id}:${j.status}`,
    )
    .join("|");
  const remoteProject = useRemote<ProjectDetail>(
    activeProject && revisionId
      ? `/projects/${activeProject}?revision_id=${revisionId}`
      : null,
    refresh,
  );
  const [chatRefresh, setChatRefresh] = useState(0);
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      setChatRefresh(
        /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (value) =>
          value + 1,
      );
    },
    [statusKey],
  );
  const remoteChat = useRemote<ConversationDetail>(
    conversationId ? `/conversations/${conversationId}` : null,
    refresh + chatRefresh,
  );

  /** 刷新工作台聚合数据；首次加载时校验本地组合并选择初始项目。 */
  const reload = useCallback(async () => {
    const value = await api<State>("/state");
    setState(value);
    setLoaded(true);
    if (!initialized.current) {
      initialized.current = true;
      const cached = loadLocal<Resume>("rm.resume.last", NEW_RESUME);
      const valid =
        cached.items.every(
          /* 检查条目是否满足当前选择或校验条件。 */ (item) =>
            value.projects.some(
              /* 检查条目是否满足当前选择或校验条件。 */ (p) =>
                p.id === item.project_id,
            ),
        ) &&
        (!cached.id ||
          value.resumes.some(
            /* 检查条目是否满足当前选择或校验条件。 */ (r) =>
              r.id === cached.id,
          ));
      const initial =
        valid && (cached.id || cached.items.length)
          ? cached
          : (value.resumes[0] ?? {
              ...NEW_RESUME,
              template_id: value.templates[0]?.id ?? null,
            });
      setDraft(initial);
      if (value.projects[0]) {
        setActiveProject(value.projects[0].id);
        setSelectedRevisions({
          [value.projects[0].id]: value.projects[0].head_revision,
        });
      }
    }
  }, []);

  const {
    draft,
    setDraft,
    exported,
    setExported,
    exporting,
    applyVersion,
    toggleProject,
    toggleHighlight,
    saveComposition,
    exportResume,
  } = useResumeComposition({
    state,
    activeProject,
    revisionId,
    revisionCache,
    setRevisionCache,
    reload,
    run,
    notify: setToast,
  });

  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      let stopped = false,
        timer: ReturnType<typeof setTimeout>;
      /** 串行轮询服务器状态，避免请求堆叠，并在卸载后停止定时器。 */
      async function poll() {
        try {
          await reload();
        } catch (e) {
          if (!stopped) setToast({ text: (e as Error).message, error: true });
        }
        if (!stopped) timer = setTimeout(poll, 1600);
      }
      void poll();
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () => {
        stopped = true;
        clearTimeout(timer);
      };
    },
    [reload],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (!activeProject && state.projects[0]) {
        setActiveProject(state.projects[0].id);
        setSelectedRevisions(
          /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
            ...v,
            [state.projects[0].id]: state.projects[0].head_revision,
          }),
        );
      }
    },
    [activeProject, state.projects],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (remoteProject.data)
        setRevisionCache(
          /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (old) => ({
            ...old,
            ...Object.fromEntries(
              remoteProject.data!.revisions.map(
                /* 逐项转换数据，保留当前业务需要的字段。 */ (r) => [r.id, r],
              ),
            ),
          }),
        );
    },
    [remoteProject.data],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      const missing = draft.items.filter(
        /* 保留满足当前范围或有效性条件的条目。 */ (i) =>
          !revisionCache[i.revision_id],
      );
      if (missing.length)
        void Promise.all(
          missing.map(
            /* 按稳定标识生成对应的列表条目。 */ (i) =>
              api<Revision>(`/revisions/${i.revision_id}`),
          ),
        )
          .then(
            /* 在异步操作成功后同步结果及相关状态。 */ (values) =>
              setRevisionCache(
                /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                  previous,
                ) => ({
                  ...previous,
                  ...Object.fromEntries(
                    values.map(
                      /* 逐项转换数据，保留当前业务需要的字段。 */ (r) => [
                        r.id,
                        r,
                      ],
                    ),
                  ),
                }),
              ),
          )
          .catch(
            /* 保留可展示的失败原因，并避免已取消请求更新页面。 */ (e) =>
              setToast({ text: e.message, error: true }),
          );
    },
    [draft.items, revisionCache],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (!toast || toast.error) return;
      const timer = setTimeout(
        /* 延迟执行保存或提示清理，减少频繁更新。 */ () => setToast(null),
        4500,
      );
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        clearTimeout(timer);
    },
    [toast],
  );

  /** 先刷新待保存草稿再执行用户操作，将异常统一显示为页面提示。 */
  function run(work: () => Promise<void>) {
    void (
      /* 执行当前异步流程，保持请求结果与所属组件状态一致。 */ (async () => {
        try {
          await flushDrafts();
          await work();
        } catch (error) {
          setToast({ text: (error as Error).message, error: true });
        }
      })()
    );
  }
  /** 清除当前编辑标记并刷新项目详情和工作台聚合数据。 */
  function changed() {
    setEdited(
      /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (value) => ({
        ...value,
        [`${activeProject}.${revisionId}`]: false,
      }),
    );
    setRefresh(
      /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => v + 1,
    );
    void reload();
  }
  /** 保存待处理草稿后切换项目或会话，用序号防止旧导航覆盖新选择。 */
  function navigate(projectId: string, convId?: string) {
    const serial = ++navigation.current;
    run(
      /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
        if (serial !== navigation.current) return;
        setActiveProject(projectId);
        setMode(convId ? "chat" : "edit");
        const head = state.projects.find(
          /* 定位与当前标识或条件匹配的条目。 */ (p) => p.id === projectId,
        )!.head_revision;
        setSelectedRevisions(
          /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
            ...v,
            [projectId]: v[projectId] ?? head,
          }),
        );
        if (convId)
          setSelectedConversations(
            /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
              ...v,
              [projectId]: convId,
            }),
          );
        setFolded(
          /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
            ...v,
            [projectId]: false,
          }),
        );
      },
    );
  }
  /** 防止重复创建会话，成功后仅在导航选择未变化时切换到新会话。 */
  async function newConversation(projectId: string) {
    if (conversationCreationPending.current) return;
    conversationCreationPending.current = true;
    setCreatingConversation(projectId);
    const serial = ++navigation.current;
    try {
      const conv = await api<Conversation>(
        `/projects/${projectId}/conversations`,
        "POST",
      );
      await reload();
      // 请求期间切换了项目时，保留用户后来的导航选择。
      if (serial !== navigation.current) return;
      setActiveProject(projectId);
      setSelectedConversations(
        /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
          ...v,
          [projectId]: conv.id,
        }),
      );
      setMode("chat");
      setFolded(
        /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
          ...v,
          [projectId]: false,
        }),
      );
    } finally {
      conversationCreationPending.current = false;
      setCreatingConversation("");
    }
  }
  /** 归档指定会话并清除其选中状态，再刷新工作台数据。 */
  async function archiveConversation(projectId: string, id: string) {
    await api(`/conversations/${id}`, "PATCH", { archived: true });
    if (selectedConversations[projectId] === id)
      setSelectedConversations(
        /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (value) => {
          const next = { ...value };
          delete next[projectId];
          return next;
        },
      );
    changed();
  }
  /** 复用当前项目的会话；尚无会话时创建并返回独立标识。 */
  async function ensureConversation() {
    if (conversationId) return conversationId;
    const conv = await api<Conversation>(
      `/projects/${activeProject}/conversations`,
      "POST",
    );
    setSelectedConversations(
      /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
        ...v,
        [activeProject]: conv.id,
      }),
    );
    await reload();
    return conv.id;
  }
  /** 把讨论范围绑定到指定亮点，并打开当前项目的 AI 会话。 */
  async function ask(scope: string) {
    const id = await ensureConversation();
    await api(`/conversations/${id}`, "PATCH", { scope });
    setMode("chat");
    changed();
  }
  /** 提交绑定经历版本和范围的消息，以唯一请求标识防止重复入队。 */
  async function send(text: string, scope: string, kind = "chat") {
    const id = await ensureConversation();
    await api(`/conversations/${id}/messages`, "POST", {
      text,
      scope,
      kind,
      base_revision: revisionId,
      request_key: crypto.randomUUID(),
    });
    setMode("chat");
    changed();
  }
  /** 发布指定草稿字段，更新本地修订缓存，但不自动改变简历固定引用。 */
  async function saveField(field: string) {
    const detail = remoteProject.data;
    if (!detail) return;
    const result = await api<Revision>(
      `/projects/${activeProject}/revisions`,
      "POST",
      {
        base_revision: revisionId,
        field,
        expected_head: detail.project.head_revision,
      },
    );
    clearLocalDrafts(activeProject, revisionId);
    setSelectedRevisions(
      /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
        ...v,
        [activeProject]: result.id,
      }),
    );
    setRevisionCache(
      /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
        ...v,
        [result.id]: result,
      }),
    );
    changed();
    setToast({
      text:
        result.id === revisionId
          ? field === "experience"
            ? `全部内容已保存，与 r${result.number} 一致，无需新建版本。`
            : `这项内容与 r${result.number} 一致，无需新建版本。`
          : `已保存为 r${result.number}。点击“用于当前简历”可更新右侧组合。`,
    });
  }
  /** 把 AI 建议放入对应版本草稿，并切回经历编辑供用户确认。 */
  async function adopt(proposal: Proposal) {
    await api(`/proposals/${proposal.id}/adopt`, "POST");
    setSelectedRevisions(
      /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
        ...v,
        [activeProject]: proposal.base_revision,
      }),
    );
    setMode("edit");
    changed();
    setToast({ text: "建议已放入草稿，可继续修改后保存。" });
  }
  /** 根据制作指引切换到目标项目或设置，再定位到对应操作控件。 */
  function followGuide(target: GuideTarget, projectId?: string) {
    setPreviewFocused(false);
    if (target === "projects" || !project) {
      setModal("projects");
      return;
    }
    if (target === "template-select" && !state.templates.length) {
      setModal("templates");
      return;
    }
    run(
      /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
        if (projectId) {
          const next = state.projects.find(
            /* 定位与当前标识或条件匹配的条目。 */ (p) => p.id === projectId,
          );
          if (!next) return;
          setActiveProject(projectId);
          setSelectedRevisions(
            /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
              value,
            ) => ({
              ...value,
              [projectId]: next.head_revision,
            }),
          );
        }
        if (["analysis", "experience-save", "experience-use"].includes(target))
          setMode(target === "analysis" && currentJob ? "chat" : "edit");
        if (matchMedia("(max-width: 600px)").matches) setSidebar(false);
        setGuideTarget(target);
      },
    );
  }
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (!guideTarget) return;
      const element = document.querySelector<HTMLElement>(
        `[data-guide="${guideTarget}"]`,
      );
      if (!element) return;
      const target =
        element instanceof HTMLButtonElement && element.disabled
          ? (element.closest<HTMLElement>("header") ?? element)
          : element;
      if (target !== element) target.tabIndex = -1;
      target.scrollIntoView({ block: "center", inline: "nearest" });
      target.focus({ preventScroll: true });
      setGuideTarget(null);
    },
    [guideTarget, mode, remoteProject.ready, activeProject],
  );
  const workflow = getWorkflow({
    projectCount: state.projects.length,
    detail: remoteProject.ready ? remoteProject.data : null,
    revisionId,
    edited: !!edited[`${activeProject}.${revisionId}`],
    draft,
    saved: state.resumes.find(
      /* 定位与当前标识或条件匹配的条目。 */ (r) => r.id === draft.id,
    ),
    revisions: revisionCache,
    result: exported,
    exporting,
    analyzing: !!currentJob,
  });
  const error = remoteProject.error || remoteChat.error;
  return (
    <div
      className={`app-shell ${sidebar ? "" : "sidebar-hidden"} ${previewFocused ? "preview-focused" : ""}`}
      style={
        {
          "--sidebar-width": `${columns.sidebar}px`,
          "--composer-width": `${columns.composer}px`,
          "--guide-height": `${clamp(layout.guide, guideMin, guideMax)}px`,
          "--editor-height": `${clamp(layout.editor, 280, 1000)}px`,
        } as CSSProperties
      }
    >
      <header className="app-header">
        <div className="row">
          <button
            className="icon-button"
            aria-label="切换侧边栏"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                setSidebar(!sidebar)
            }
          >
            <PanelLeftClose size={19} />
          </button>
          <strong>Resume Maker</strong>
          <span className="subtle app-subtitle">项目经历工作台</span>
        </div>
        <div className="row header-actions">
          {activeJobs.length > 0 && (
            <span className="subtle header-job-status">
              <LoaderCircle className="spin" size={14} /> {activeJobs.length}{" "}
              个任务进行中
            </span>
          )}
          <ThemeSwitch />
          <button
            className="icon-button"
            aria-label="重置布局"
            title="重置各区域大小"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () => {
                setLayout({ ...DEFAULT_LAYOUT });
                setSidebar(!matchMedia("(max-width: 600px)").matches);
                setPreviewFocused(false);
              }
            }
          >
            <RotateCcw size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="刷新数据"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                run(
                  /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                    await reload();
                    changed();
                  },
                )
            }
          >
            <RefreshCw size={17} />
          </button>
          <button
            className="icon-button"
            aria-label="打开设置"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                setModal("settings")
            }
          >
            <SettingsIcon size={18} />
          </button>
        </div>
      </header>
      <div
        className={`guide-container ${layout.guideCollapsed ? "guide-collapsed" : ""}`}
      >
        <Workflow
          value={workflow}
          onNavigate={followGuide}
          collapsed={layout.guideCollapsed}
          onToggle={
            /* 处理 onToggle 回调，将变化同步到工作台状态。 */ () =>
              resize("guideCollapsed", !layout.guideCollapsed)
          }
        />
        {!layout.guideCollapsed && (
          <ResizeHandle
            className="guide-resize"
            label="调整制作指引高度"
            axis="y"
            value={clamp(layout.guide, guideMin, guideMax)}
            min={guideMin}
            max={guideMax}
            onChange={
              /* 把控件的新值同步到对应编辑状态。 */ (value) =>
                resize("guide", value)
            }
            onReset={
              /* 恢复该区域的默认布局尺寸。 */ () =>
                resize("guide", DEFAULT_LAYOUT.guide)
            }
          />
        )}
      </div>
      <div className="workbench" ref={workbench}>
        <ProjectSidebar
          projects={state.projects}
          conversations={state.conversations}
          activeJobs={activeJobs}
          items={draft.items}
          activeProject={activeProject}
          conversationId={conversationId}
          mode={mode}
          creatingConversation={creatingConversation}
          folded={folded}
          setFolded={setFolded}
          onNavigate={navigate}
          onToggleProject={toggleProject}
          onNewConversation={
            /* 处理 onNewConversation 回调，将变化同步到工作台状态。 */ (id) =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                  newConversation(id),
              )
          }
          onArchive={
            /* 处理 onArchive 回调，将变化同步到工作台状态。 */ (
              projectId,
              id,
            ) =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                  archiveConversation(projectId, id),
              )
          }
          onImport={
            /* 处理 onImport 回调，将变化同步到工作台状态。 */ () =>
              setModal("projects")
          }
        />
        <ResizeHandle
          className="sidebar-resize"
          label="调整项目栏宽度"
          axis="x"
          value={columns.sidebar}
          min={160}
          max={columns.sidebarMax}
          onChange={
            /* 把控件的新值同步到对应编辑状态。 */ (value) =>
              resize("sidebar", value)
          }
          onReset={
            /* 恢复该区域的默认布局尺寸。 */ () =>
              resize("sidebar", DEFAULT_LAYOUT.sidebar)
          }
        />
        <main className="workspace">
          {!loaded ? (
            <div className="empty">
              <LoaderCircle className="spin" />
              正在读取本机数据…
            </div>
          ) : !project ? (
            <div className="empty welcome">
              <span className="eyebrow">从你的项目开始</span>
              <h1>把项目积累，变成可复用的经历。</h1>
              <p>
                导入源码目录，让 Codex
                提取项目事实；编辑每条亮点，再组合成简历。
              </p>
              <button
                className="primary"
                onClick={
                  /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                    setModal("projects")
                }
              >
                <FolderPlus size={17} />
                导入项目集合
              </button>
            </div>
          ) : (
            <>
              <header className="workspace-header">
                <div>
                  <h1
                    title={
                      remoteProject.data?.working.content.title || project.name
                    }
                  >
                    {remoteProject.data?.working.content.title || project.name}
                  </h1>
                </div>
                <nav className="tabs workspace-tabs" aria-label="项目工作区">
                  <button
                    className={mode === "edit" ? "active" : ""}
                    aria-current={mode === "edit" ? "page" : undefined}
                    onClick={
                      /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                        run(
                          /* 在草稿刷新成功后执行当前业务操作。 */ async () =>
                            setMode("edit"),
                        )
                    }
                  >
                    经历编辑
                  </button>
                  <button
                    className={mode === "chat" ? "active" : ""}
                    aria-current={mode === "chat" ? "page" : undefined}
                    onClick={
                      /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                        run(
                          /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                            await ensureConversation();
                            setMode("chat");
                          },
                        )
                    }
                  >
                    AI 会话
                  </button>
                </nav>
                <button
                  data-guide="analysis"
                  aria-label={
                    remoteProject.data?.working.content.highlights.length
                      ? "重新分析源码"
                      : "分析项目"
                  }
                  title={
                    remoteProject.data?.working.content.highlights.length
                      ? "重新分析源码"
                      : "分析项目"
                  }
                  disabled={!!currentJob || !remoteProject.data}
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      run(
                        /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                          send(
                            "请读取当前项目源码和材料，生成有证据支持的完整项目经历草稿。未确认的个人贡献、参与日期和量化成果请列为问题。",
                            "all",
                            "analysis",
                          ),
                      )
                  }
                >
                  <Sparkles size={16} />
                  <span className="analysis-label">
                    {remoteProject.data?.working.content.highlights.length
                      ? "重新分析源码"
                      : "分析项目"}
                  </span>
                </button>
              </header>
              <div className="workspace-scroll">
                {error && <div className="error-panel">{error}</div>}
                {!remoteProject.data ? (
                  <div className="empty compact">正在读取项目…</div>
                ) : mode === "edit" ? (
                  remoteProject.ready ? (
                    <Editor
                      key={`${activeProject}.${revisionId}.${refresh}`}
                      detail={remoteProject.data}
                      revisionId={revisionId}
                      hasLocalChanges={
                        !!edited[`${activeProject}.${revisionId}`]
                      }
                      usedRevision={
                        revisionCache[
                          draft.items.find(
                            /* 定位与当前标识或条件匹配的条目。 */ (item) =>
                              item.project_id === activeProject,
                          )?.revision_id ?? ""
                        ]
                      }
                      included={
                        draft.items.find(
                          /* 定位与当前标识或条件匹配的条目。 */ (i) =>
                            i.project_id === activeProject,
                        )?.highlight_ids ?? []
                      }
                      run={run}
                      onSave={saveField}
                      onRefresh={changed}
                      onDirty={
                        /* 标记尚未发布的本机修改，更新制作指引状态。 */ () =>
                          setEdited(
                            /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                              value,
                            ) => ({
                              ...value,
                              [`${activeProject}.${revisionId}`]: true,
                            }),
                          )
                      }
                      onRevision={
                        /* 处理 onRevision 回调，将变化同步到工作台状态。 */ (
                          id,
                        ) =>
                          run(
                            /* 在草稿刷新成功后执行当前业务操作。 */ async () =>
                              setSelectedRevisions(
                                /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                                  v,
                                ) => ({
                                  ...v,
                                  [activeProject]: id,
                                }),
                              ),
                          )
                      }
                      onUseVersion={applyVersion}
                      onAsk={ask}
                      onToggle={toggleHighlight}
                    />
                  ) : (
                    <div className="empty compact">正在读取草稿…</div>
                  )
                ) : remoteChat.data ? (
                  <Chat
                    key={conversationId}
                    inputHeight={layout.chatInput}
                    onInputHeight={
                      /* 处理 onInputHeight 回调，将变化同步到工作台状态。 */ (
                        value,
                      ) => resize("chatInput", value)
                    }
                    detail={remoteChat.data}
                    project={remoteProject.data}
                    activeJob={currentJob}
                    run={run}
                    onSend={send}
                    onAdopt={adopt}
                    onRefresh={changed}
                  />
                ) : (
                  <div className="empty compact">正在读取会话…</div>
                )}
              </div>
            </>
          )}
        </main>
        <ResizeHandle
          className="composer-resize"
          label="调整简历区宽度"
          axis="x"
          reverse
          value={columns.composer}
          min={300}
          max={columns.composerMax}
          onChange={
            /* 把控件的新值同步到对应编辑状态。 */ (value) =>
              resize("composer", value)
          }
          onReset={
            /* 恢复该区域的默认布局尺寸。 */ () =>
              resize("composer", DEFAULT_LAYOUT.composer)
          }
        />
        <ResizeHandle
          className="stack-resize"
          label="调整编辑区高度"
          axis="y"
          value={clamp(layout.editor, 280, 1000)}
          min={280}
          max={1000}
          onChange={
            /* 把控件的新值同步到对应编辑状态。 */ (value) =>
              resize("editor", value)
          }
          onReset={
            /* 恢复该区域的默认布局尺寸。 */ () =>
              resize("editor", DEFAULT_LAYOUT.editor)
          }
        />
        <Composer
          settingsHeight={layout.settings}
          onSettingsHeight={
            /* 处理 onSettingsHeight 回调，将变化同步到工作台状态。 */ (
              value,
            ) => resize("settings", value)
          }
          previewFocused={previewFocused}
          onFocusPreview={
            /* 处理 onFocusPreview 回调，将变化同步到工作台状态。 */ () =>
              setPreviewFocused(!previewFocused)
          }
          state={state}
          draft={draft}
          revisions={revisionCache}
          result={exported}
          exporting={exporting}
          onChange={setDraft}
          onChoose={
            /* 处理 onChoose 回调，将变化同步到工作台状态。 */ (id) =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                  const resume = state.resumes.find(
                    /* 定位与当前标识或条件匹配的条目。 */ (r) => r.id === id,
                  );
                  if (resume) {
                    setDraft(loadLocal(`rm.resume.${id}`, resume));
                    setExported(null);
                  }
                },
              )
          }
          onSave={
            /* 处理 onSave 回调，将变化同步到工作台状态。 */ () =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                  await saveComposition();
                  setToast({ text: "简历组合已保存，引用版本已固定。" });
                },
              )
          }
          onExport={
            /* 处理 onExport 回调，将变化同步到工作台状态。 */ () =>
              run(exportResume)
          }
          onNew={
            /* 处理 onNew 回调，将变化同步到工作台状态。 */ () =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                  const value = await api<Resume>("/resumes", "POST", {
                    name: "新简历",
                    template_id: state.templates[0]?.id ?? null,
                    items: [],
                  });
                  await reload();
                  setDraft(value);
                  setExported(null);
                },
              )
          }
          onTemplates={
            /* 处理 onTemplates 回调，将变化同步到工作台状态。 */ () =>
              setModal("templates")
          }
          onEditProject={
            /* 处理 onEditProject 回调，将变化同步到工作台状态。 */ (id) =>
              followGuide("experience-use", id)
          }
          run={run}
        />
      </div>
      {modal && (
        <Settings
          initial={modal}
          onClose={
            /* 处理 onClose 回调，将变化同步到工作台状态。 */ () =>
              setModal(null)
          }
          onChanged={
            /* 处理 onChanged 回调，将变化同步到工作台状态。 */ async () => {
              await reload();
              changed();
            }
          }
          run={run}
        />
      )}
      {toast && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          <span>{toast.text}</span>
          <button
            className="icon-button"
            aria-label="关闭提示"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () => setToast(null)
            }
          >
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
