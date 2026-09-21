import {
  FileDown,
  FilePenLine,
  FileScan,
  FolderPlus,
  LoaderCircle,
  PanelLeftOpen,
  RefreshCw,
  RotateCcw,
  Settings as SettingsIcon,
  Sparkles,
  X,
  UserRound,
  PanelsTopLeft,
  ListTree,
  Award,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import Chat from "../features/conversations/Chat";
import Editor from "../features/experiences/Editor";
import { clearLocalDrafts } from "../features/experiences/useField";
import { experienceContent } from "../features/experiences/visibility";
import ProjectSidebar from "../features/projects/ProjectSidebar";
import DeleteProjectDialog from "../features/projects/DeleteProjectDialog";
import {
  projectDeletionBlocker,
  projectDeletionIds,
} from "../features/projects/deletion";
import {
  expandProjectPath,
  restoreSidebarSort,
  sortSidebar,
} from "../features/projects/sort";
import Composer from "../features/resumes/Composer";
import ResumeLibrary from "../features/resumes/ResumeLibrary";
import { sameComposition } from "../features/resumes/composition";
import ProjectOrder from "../features/resumes/ProjectOrder";
import ProfileEditor from "../features/profile/ProfileEditor";
import HonorLibrary from "../features/honors/HonorLibrary";
import HonorEditor from "../features/honors/HonorEditor";
import { addHonors, removeHonor, type Honor } from "../features/honors/model";
import { syncHonorResume } from "../features/honors/sync";
import { entryWithHonorFields } from "../features/honors/entry";
import DefaultsDialog from "../features/profile/defaults/Dialog";
import { applyResumeDefaults } from "../features/profile/defaults/model";
import SectionOrganizer from "../features/profile/SectionOrganizer";
import { newDocument } from "../features/profile/document";
import {
  NEW_RESUME,
  useResumeComposition,
} from "../features/resumes/useResumeComposition";
import TemplateAdapter from "../features/templates/TemplateAdapter";
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
  Experience,
  ProjectDetail,
  Project,
  Proposal,
  Resume,
  ResumeDefaults,
  Revision,
  State,
  SectionEntry,
} from "../shared/types/index";
import { useWorkspaceLayout } from "./useWorkspaceLayout";

const EMPTY: State = {
  honors: [],
  branches: [],
  projects: [],
  conversations: [],
  resumes: [],
  templates: [],
  jobs: [],
};
/** 组装工作台并协调项目导航、经历发布、会话和简历组合之间的状态 */
export default function App() {
  const [area, setArea] = useState<
    "projects" | "personal" | "structure" | "templates" | "honors"
  >("projects");
  const [defaultsOpen, setDefaultsOpen] = useState(false);
  const [resumeLibraryOpen, setResumeLibraryOpen] = useState(false);
  const [structureTarget, setStructureTarget] = useState<string | null>(null);
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
  const sidebarToggleRequested = useRef(false);
  useEffect(
    /* 手动折叠或展开后，将键盘焦点交还给当前可见的切换入口 */ () => {
      if (!sidebarToggleRequested.current) return;
      sidebarToggleRequested.current = false;
      document
        .getElementById(sidebar ? "sidebar-collapse" : "sidebar-expand")
        ?.focus({ preventScroll: true });
    },
    [sidebar],
  );
  /** 切换项目库显隐并在渲染后恢复操作按钮的焦点 */
  function toggleSidebar() {
    sidebarToggleRequested.current = true;
    setSidebar(/* 基于最近状态切换以免连续操作覆盖 */ (visible) => !visible);
  }
  const [state, setState] = useState<State>(EMPTY),
    [loaded, setLoaded] = useState(false);
  const [editingHonor, setEditingHonor] = useState<{
    honor: Honor | null;
    resumeId: string;
    sectionId: string;
    entry: SectionEntry;
  } | null>(null);
  const stateRequests = useRef(0);
  const [activeProject, setActiveProject] = useState("");
  const [sidebarSort, setSidebarSort] = useState(
    /* 恢复排序偏好，使首次打开的项目和侧栏首项一致 */ () =>
      restoreSidebarSort(loadLocal("rm.sidebarSort", "recent")),
  );
  const sortedSidebar = useMemo(
    /* 侧栏展示和默认项目选择共用同一份排序结果 */ () =>
      sortSidebar(state.projects, state.conversations, sidebarSort),
    [state.projects, state.conversations, sidebarSort],
  );
  const firstProject = sortedSidebar.rootProjects[0];
  useEffect(
    /* 记住用户选择的排序方式，供下次打开页面使用 */ () => {
      localStorage.setItem("rm.sidebarSort", JSON.stringify(sidebarSort));
    },
    [sidebarSort],
  );
  const [selectedRevisions, setSelectedRevisions] = useState<
    Record<string, string>
  >({});
  const [selectedConversations, setSelectedConversations] = useState<
    Record<string, string>
  >({});
  const [creatingConversation, setCreatingConversation] = useState("");
  const [deletingProject, setDeletingProject] = useState<Project | null>(null);
  const conversationCreationPending = useRef(false);
  const [mode, setMode] = useState<"edit" | "chat">("edit");
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  const [guideTarget, setGuideTarget] = useState<GuideTarget | null>(null);
  const [modal, setModal] = useState<"projects" | "settings" | null>(null);
  const [refresh, setRefresh] = useState(0),
    [toast, setToast] = useState<{ text: string; error?: boolean } | null>(
      null,
    );
  const [revisionCache, setRevisionCache] = useState<Record<string, Revision>>(
    {},
  );
  const [workingPreviews, setWorkingPreviews] = useState<
    Record<string, Experience>
  >({});
  /** 接收各修订的编辑副本，保持正式版本缓存不变 */
  const updateWorkingPreview = useCallback(
    /* 各修订的编辑副本单独用于预览 */ (id: string, content: Experience) => {
      setWorkingPreviews(
        /* 相同副本不触发额外渲染 */ (values) =>
          values[id] === content ? values : { ...values, [id]: content },
      );
    },
    [],
  );
  const initialized = useRef(false),
    navigation = useRef(0);
  const project = state.projects.find((p) => p.id === activeProject);
  const parentProject = state.projects.find(
    /* 识别当前子项目所属的整体项目，用于范围提示和返回导航 */ (p) =>
      p.id === project?.parent_id,
  );
  const revisionId =
    selectedRevisions[activeProject] ?? project?.head_revision ?? "";
  const conversationId =
    selectedConversations[activeProject] ??
    state.conversations.find((c) => c.project_id === activeProject)?.id ??
    "";
  const activeJobs = state.jobs.filter((j) =>
    ["running", "queued"].includes(j.status),
  );
  const currentJob = activeJobs.find(
    (j) => j.conversation_id === conversationId,
  );
  const statusKey = state.jobs
    .filter((j) => j.conversation_id === conversationId)
    .map((j) => `${j.id}:${j.status}`)
    .join("|");
  const remoteProject = useRemote<ProjectDetail>(
    activeProject && revisionId
      ? `/projects/${activeProject}?revision_id=${revisionId}`
      : null,
    refresh,
  );
  const [chatRefresh, setChatRefresh] = useState(0);
  useEffect(() => {
    setChatRefresh((value) => value + 1);
  }, [statusKey]);
  const remoteChat = useRemote<ConversationDetail>(
    conversationId ? `/conversations/${conversationId}` : null,
    refresh + chatRefresh,
  );

  /** 刷新工作台聚合数据，首次加载时校验并恢复本地组合 */
  const reload = useCallback(async () => {
    const request = ++stateRequests.current;
    const value = await api<State>("/state");
    if (request !== stateRequests.current) return;
    setState(value);
    setLoaded(true);
    if (!initialized.current) {
      initialized.current = true;
      const cached = loadLocal<Resume>("rm.resume.v2.last", {
        ...NEW_RESUME,
        document: newDocument(value.resume_defaults),
      });
      const valid =
        cached.items.every((item) =>
          value.projects.some((p) => p.id === item.project_id),
        ) &&
        (!cached.id || value.resumes.some((r) => r.id === cached.id));
      const initial =
        valid && (cached.id || cached.items.length || cached.document)
          ? cached
          : (value.resumes[0] ?? {
              ...NEW_RESUME,
              document: newDocument(value.resume_defaults),
            });
      setDraft(initial);
    }
  }, []);

  /** 从任一入口保存荣誉后立即更新共享内容，使在途旧轮询失效 */
  function honorSaved(honor: Honor) {
    ++stateRequests.current;
    const source = {
      id: honor.id,
      fields: honor.fields,
      reviewed: honor.reviewed,
      version: honor.version,
      updated_at: honor.updated_at,
    };
    setState(
      /* 只更新来源资料，简历中的排序、显隐和其他草稿由原状态保留 */ (
        current,
      ) => {
        if (
          (current.honors ?? []).some(
            /* 迟到保存响应不能覆盖其他窗口已经保存的更高版本 */ (item) =>
              item.id === source.id && item.version > source.version,
          )
        )
          return current;
        return {
          ...current,
          honors: [
            source,
            ...(current.honors ?? []).filter(
              /* 替换同一来源的旧版本 */ (item) => item.id !== honor.id,
            ),
          ],
          resumes: current.resumes.map(
            /* 当前和其他方案都读取同一份核对内容 */ (resume) =>
              syncHonorResume(resume, [source]),
          ),
        };
      },
    );
  }

  /** 打开最新来源和当前简历草稿并在取消时保留原值 */
  async function editLinkedHonor(
    id: string,
    sectionId: string,
    entry: SectionEntry,
  ) {
    try {
      const items = id ? await api<Honor[]>("/honors") : [];
      const honor =
        items.find(
          /* 按来源标识查找，重名条目互不影响 */ (item) => item.id === id,
        ) ?? null;
      setEditingHonor({
        honor,
        resumeId: draft.id,
        sectionId,
        entry: honor ? entryWithHonorFields(entry, honor.fields) : entry,
      });
    } catch (error) {
      setToast({ text: (error as Error).message, error: true });
    }
  }

  const {
    draft,
    setDraft,
    exported,
    setExported,
    exporting,
    deleting,
    applyVersion,
    toggleProject,
    toggleHighlight,
    changeProjectVisibility,
    saveComposition,
    savePersonalInfo,
    saveSectionEntry,
    deleteComposition,
    exportResume,
    previewSources,
    previewChanged,
  } = useResumeComposition({
    state,
    activeProject,
    revisionId,
    revisionCache,
    workingPreviews,
    setRevisionCache,
    reload,
    run,
    notify: setToast,
  });
  const deletingProjectIds = projectDeletionIds(
    state.projects,
    deletingProject?.id ?? "",
  );
  const deletionBlocker = projectDeletionBlocker(
    deletingProjectIds,
    state.resumes,
    draft,
    state.jobs,
  );

  useEffect(() => {
    let stopped = false,
      timer: ReturnType<typeof setTimeout>;
    /** 串行轮询服务器状态并在卸载后清除定时器 */
    async function poll() {
      try {
        await reload();
      } catch (e) {
        if (!stopped) setToast({ text: (e as Error).message, error: true });
      }
      if (!stopped) timer = setTimeout(poll, 1600);
    }
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [reload]);
  useEffect(
    /* 首次加载或当前项目被删除时选择有效项目 */ () => {
      if (!loaded || state.projects.some((item) => item.id === activeProject))
        return;
      if (firstProject) {
        setActiveProject(firstProject.id);
        setMode("edit");
        setSelectedRevisions((v) => ({
          ...v,
          [firstProject.id]: firstProject.head_revision,
        }));
      } else if (activeProject) {
        setActiveProject("");
        setMode("edit");
      }
    },
    [activeProject, firstProject, loaded, state.projects],
  );
  useEffect(() => {
    if (remoteProject.data)
      setRevisionCache((old) => ({
        ...old,
        ...Object.fromEntries(
          remoteProject.data!.revisions.map((r) => [r.id, r]),
        ),
      }));
  }, [remoteProject.data]);
  useEffect(() => {
    const missing = draft.items.filter((i) => !revisionCache[i.revision_id]);
    if (missing.length)
      void Promise.all(
        missing.map((i) => api<Revision>(`/revisions/${i.revision_id}`)),
      )
        .then((values) =>
          setRevisionCache((previous) => ({
            ...previous,
            ...Object.fromEntries(values.map((r) => [r.id, r])),
          })),
        )
        .catch(
          /* 取消后忽略迟到的错误 */ (e) =>
            setToast({ text: e.message, error: true }),
        );
  }, [draft.items, revisionCache]);
  useEffect(() => {
    if (!toast || toast.error) return;
    const timer = setTimeout(
      /* 延迟执行保存或提示清理，减少频繁更新 */ () => setToast(null),
      4500,
    );
    return () => clearTimeout(timer);
  }, [toast]);

  /** 等待草稿保存后执行操作并显示异常提示 */
  function run(work: () => Promise<void>) {
    void (
      /* 执行当前异步流程，保持请求结果和所属组件状态一致 */ (async () => {
        try {
          await flushDrafts();
          await work();
        } catch (error) {
          setToast({ text: (error as Error).message, error: true });
        }
      })()
    );
  }
  /** 刷新项目详情和工作台数据，由当前内容重新计算编辑状态 */
  function changed() {
    setRefresh((v) => v + 1);
    void reload();
  }
  /** 保存待处理草稿后切换项目或会话，用序号防止旧导航覆盖新选择 */
  function navigate(projectId: string, convId?: string) {
    const serial = ++navigation.current;
    run(async () => {
      if (serial !== navigation.current) return;
      setArea("projects");
      setActiveProject(projectId);
      setMode(convId ? "chat" : "edit");
      const head = state.projects.find(
        (p) => p.id === projectId,
      )!.head_revision;
      setSelectedRevisions((v) => ({
        ...v,
        [projectId]: v[projectId] ?? head,
      }));
      if (convId)
        setSelectedConversations((v) => ({
          ...v,
          [projectId]: convId,
        }));
      setFolded(
        /* 展开子项目和所属项目以显示导航位置 */ (v) =>
          expandProjectPath(state.projects, projectId, v),
      );
    });
  }
  /** 防止重复创建会话，成功后仅在导航选择未变化时切换到新会话 */
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
      // 请求期间切换了项目时，保留用户后来的导航选择
      if (serial !== navigation.current) return;
      setActiveProject(projectId);
      setSelectedConversations((v) => ({
        ...v,
        [projectId]: conv.id,
      }));
      setMode("chat");
      setFolded(
        /* 新会话始终留在对应子项目下并展开它的分组 */ (v) =>
          expandProjectPath(state.projects, projectId, v),
      );
    } finally {
      conversationCreationPending.current = false;
      setCreatingConversation("");
    }
  }
  /** 归档指定会话并清除其选中状态，再刷新工作台数据 */
  async function archiveConversation(projectId: string, id: string) {
    await api(`/conversations/${id}`, "PATCH", { archived: true });
    if (selectedConversations[projectId] === id)
      setSelectedConversations((value) => {
        const next = { ...value };
        delete next[projectId];
        return next;
      });
    changed();
  }
  /** 等待草稿写入并完成服务端删除后清理列表和导航缓存 */
  async function deleteProject() {
    if (!deletingProject) return;
    if (deletionBlocker) throw new Error(deletionBlocker);
    await flushDrafts();
    const result = await api<{ deleted_project_ids: string[] }>(
      `/projects/${encodeURIComponent(deletingProject.id)}`,
      "DELETE",
    );
    const ids = new Set(result.deleted_project_ids);
    ++stateRequests.current;
    ++navigation.current;
    setState((current) => ({
      ...current,
      projects: current.projects.filter((item) => !ids.has(item.id)),
      conversations: current.conversations.filter(
        (item) => !ids.has(item.project_id),
      ),
      branches: current.branches.filter((item) => !ids.has(item.project_id)),
      jobs: current.jobs.filter((item) => !ids.has(item.project_id)),
    }));
    /** 清理被删除项目的导航偏好，保留其他项目当前版本和折叠状态 */
    const remaining = <T,>(values: Record<string, T>) =>
      Object.fromEntries(Object.entries(values).filter(([id]) => !ids.has(id)));
    setSelectedRevisions(remaining);
    setSelectedConversations(remaining);
    setFolded(remaining);
    if (ids.has(activeProject)) {
      setActiveProject("");
      setMode("edit");
    }
    setToast({ text: `已删除项目“${deletingProject.name}”` });
  }
  /** 复用当前项目的会话，尚无会话时创建并返回独立标识 */
  async function ensureConversation() {
    if (conversationId) return conversationId;
    const conv = await api<Conversation>(
      `/projects/${activeProject}/conversations`,
      "POST",
    );
    setSelectedConversations((v) => ({
      ...v,
      [activeProject]: conv.id,
    }));
    await reload();
    return conv.id;
  }
  /** 把讨论范围绑定到指定亮点并打开当前项目的 AI 会话 */
  async function ask(scope: string) {
    const id = await ensureConversation();
    await api(`/conversations/${id}`, "PATCH", { scope });
    setMode("chat");
    changed();
  }
  /** 提交绑定经历版本和范围的消息，以唯一请求标识防止重复入队 */
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
  /** 发布工作副本并更新修订缓存 */
  async function saveRevision() {
    const detail = remoteProject.data;
    if (!detail) return;
    const result = await api<Revision>(
      `/projects/${activeProject}/revisions`,
      "POST",
      {
        base_revision: revisionId,
        expected_head: detail.branch.head_revision,
      },
    );
    clearLocalDrafts(activeProject, revisionId);
    setWorkingPreviews(
      /* 提交后恢复旧基线的不可变内容 */ (values) => {
        const next = { ...values };
        delete next[revisionId];
        return next;
      },
    );
    setSelectedRevisions((v) => ({
      ...v,
      [activeProject]: result.id,
    }));
    setRevisionCache((v) => ({
      ...v,
      [result.id]: result,
    }));
    changed();
    setToast({
      text:
        result.id === revisionId
          ? `全部内容已保存，与 r${result.number} 一致，无需新建版本。`
          : `已提交为 r${result.number}。点击“用于当前简历”可更新右侧组合。`,
    });
  }
  /** 只撤销确认窗口对应版本的未提交改动 */
  async function discardChanges(versions: Record<string, number>) {
    await api(`/projects/${activeProject}/drafts/discard`, "POST", {
      base_revision: revisionId,
      versions,
    });
    clearLocalDrafts(activeProject, revisionId);
    setWorkingPreviews(
      /* 删除旧预览，刷新后由原版本内容重新生成 */ (values) => {
        const next = { ...values };
        delete next[revisionId];
        return next;
      },
    );
    changed();
    setToast({ text: "已撤销当前版本的未提交改动。" });
  }
  /** 把 AI 建议放入对应版本草稿并切回经历编辑供用户确认 */
  async function adopt(proposal: Proposal) {
    await api(`/proposals/${proposal.id}/adopt`, "POST");
    setSelectedRevisions((v) => ({
      ...v,
      [activeProject]: proposal.base_revision,
    }));
    setMode("edit");
    changed();
    setToast({ text: "建议已放入草稿，可继续修改后保存。" });
  }
  /** 根据制作指引切换到目标项目或设置，再定位到对应操作控件 */
  function followGuide(target: GuideTarget, projectId?: string) {
    run(async () => {
      setPreviewFocused(false);
      setResumeLibraryOpen(false);
      setGuideTarget(null);
      if (target === "template-select") {
        setArea("templates");
        setGuideTarget(target);
        return;
      }
      if (target.startsWith("personal-")) {
        setArea("personal");
        setGuideTarget(target);
        return;
      }
      if (target.startsWith("honor-")) {
        setArea("honors");
        setGuideTarget(target);
        return;
      }
      if (target === "structure") {
        setStructureTarget(null);
        setArea("structure");
        return;
      }
      if (target === "composition-save" || target === "export") {
        setResumeLibraryOpen(true);
        setGuideTarget(target);
        return;
      }
      setArea("projects");
      if (target === "projects" || (!project && !projectId)) {
        setModal("projects");
        return;
      }
      if (projectId) {
        const next = state.projects.find((p) => p.id === projectId);
        if (!next) return;
        const used = draft.items.find(
          /* 从简历返回时沿用其引用版本所属的分支 */ (item) =>
            item.project_id === projectId,
        );
        const branch = state.branches.find(
          /* 找到该简历引用的分支最新版本 */ (item) =>
            item.id === revisionCache[used?.revision_id ?? ""]?.branch_id,
        );
        setActiveProject(projectId);
        setFolded(
          /* 从简历预览返回时同步展开所属分组 */ (v) =>
            expandProjectPath(state.projects, projectId, v),
        );
        setSelectedRevisions((value) => ({
          ...value,
          [projectId]: branch?.head_revision ?? next.head_revision,
        }));
      }
      if (["analysis", "experience-save", "experience-use"].includes(target))
        setMode(target === "analysis" && currentJob ? "chat" : "edit");
      if (matchMedia("(max-width: 600px)").matches) setSidebar(false);
      setGuideTarget(target);
    });
  }
  useEffect(() => {
    if (!guideTarget) return;
    const element =
      document.querySelector<HTMLElement>(`[data-guide="${guideTarget}"]`) ??
      (guideTarget.startsWith("personal-")
        ? document.querySelector<HTMLElement>(".personal-scroll")
        : null);
    if (!element) return;
    const target =
      element instanceof HTMLButtonElement && element.disabled
        ? (element.closest<HTMLElement>("header, section") ?? element)
        : element;
    if (!target.matches("button, input, select, textarea, a[href]"))
      target.tabIndex = -1;
    // 只滚动目标所在面板以保留窄屏顶部的制作步骤
    let scrollPanel = target.parentElement;
    while (scrollPanel && scrollPanel !== document.body) {
      if (
        /auto|scroll/.test(getComputedStyle(scrollPanel).overflowY) &&
        scrollPanel.scrollHeight > scrollPanel.clientHeight
      ) {
        scrollPanel.scrollTop +=
          target.getBoundingClientRect().top -
          scrollPanel.getBoundingClientRect().top -
          12;
        break;
      }
      scrollPanel = scrollPanel.parentElement;
    }
    if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
    target.focus({ preventScroll: true });
    setGuideTarget(null);
  }, [
    guideTarget,
    mode,
    remoteProject.ready,
    activeProject,
    resumeLibraryOpen,
    area,
    loaded,
  ]);
  const currentContent =
    workingPreviews[revisionId] ?? remoteProject.data?.working.content;
  const currentBase = revisionCache[revisionId]?.content;
  const currentVisibility =
    draft.document?.project_visibility?.[activeProject] ?? {};
  const hasExperienceChanges =
    !!currentContent &&
    !!currentBase &&
    experienceContent(currentContent, currentVisibility) !==
      experienceContent(currentBase, currentVisibility);
  const workflow = getWorkflow({
    honors: state.honors,
    projectCount: state.projects.length,
    detail: remoteProject.ready ? remoteProject.data : null,
    revisionId,
    edited: hasExperienceChanges,
    draft,
    saved: state.resumes.find((r) => r.id === draft.id),
    revisions: revisionCache,
    result: exported,
    exporting,
    analyzing: !!currentJob,
  });
  const error = remoteProject.error || remoteChat.error;
  return (
    <div
      className={`app-shell ${sidebar && area === "projects" ? "" : "sidebar-hidden"} ${previewFocused ? "preview-focused" : ""} ${area === "honors" ? "honor-area" : area === "templates" ? "template-area" : area !== "projects" ? "profile-area" : ""}`}
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
        <div className="row app-brand">
          {!sidebar && !previewFocused && area === "projects" && (
            <button
              id="sidebar-expand"
              className="icon-button"
              aria-label="展开项目库"
              title="展开项目库"
              aria-expanded={false}
              aria-controls="project-sidebar"
              onClick={toggleSidebar}
            >
              <PanelLeftOpen size={19} />
            </button>
          )}
          <strong>Resume Maker</strong>
        </div>
        <nav className="area-navigation" aria-label="主要功能区">
          {(
            [
              {
                id: "projects",
                label: "项目经历",
                icon: PanelsTopLeft,
              },
              {
                id: "personal",
                label: "个人信息",
                icon: UserRound,
              },
              {
                id: "structure",
                label: "栏目编排",
                icon: ListTree,
              },
              { id: "honors", label: "荣誉证书", icon: Award },
              { id: "templates", label: "Word 模板", icon: FileScan },
            ] as const
          ).map(
            /* 每个功能区共享当前简历草稿，切换前刷新项目编辑 */ (item) => (
              <button
                key={item.id}
                className={area === item.id ? "active" : ""}
                aria-current={area === item.id ? "page" : undefined}
                onClick={
                  /* 切换主要功能区并退出放大预览 */ () =>
                    run(
                      /* 保存待处理草稿后导航 */ async () => {
                        setArea(item.id);
                        setPreviewFocused(false);
                      },
                    )
                }
              >
                <item.icon size={18} />
                <span>{item.label}</span>
              </button>
            ),
          )}
        </nav>
        <button
          className="resume-library-trigger"
          aria-label={`导出与模板：${draft.name || "未命名方案"}，打开简历库`}
          aria-haspopup="dialog"
          aria-expanded={resumeLibraryOpen}
          title={`导出与模板 · ${draft.name || "未命名方案"}`}
          onClick={
            /* 打开方案、模板和导出历史管理 */ () => setResumeLibraryOpen(true)
          }
        >
          <FileDown size={17} />
          <span className="resume-trigger-copy">
            <b>{exporting ? "正在导出…" : "导出与模板"}</b>
            <small>{draft.name || "未命名方案"}</small>
          </span>
          {!sameComposition(
            state.resumes.find(
              /* 顶部提示当前方案是否仍有未保存的修改 */ (item) =>
                item.id === draft.id,
            ),
            draft,
          ) && (
            <span
              className="resume-unsaved-dot"
              aria-label="组合未保存"
              title="组合未保存"
            />
          )}
        </button>
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
            onClick={() => {
              setLayout({ ...DEFAULT_LAYOUT });
              setSidebar(!matchMedia("(max-width: 600px)").matches);
              setPreviewFocused(false);
            }}
          >
            <RotateCcw size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="刷新数据"
            onClick={() =>
              run(async () => {
                await reload();
                changed();
              })
            }
          >
            <RefreshCw size={17} />
          </button>
          <button
            className="icon-button"
            aria-label="打开设置"
            onClick={() => setModal("settings")}
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
          activeStep={
            resumeLibraryOpen
              ? 5
              : area === "templates"
                ? 0
                : area === "personal"
                  ? 1
                  : area === "honors"
                    ? 3
                    : area === "structure"
                      ? 4
                      : 2
          }
          onNavigate={followGuide}
          collapsed={layout.guideCollapsed}
          onToggle={
            /* 处理 onToggle 回调，将变化同步到工作台状态 */ () =>
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
            onChange={(value) => resize("guide", value)}
            onReset={() => resize("guide", DEFAULT_LAYOUT.guide)}
          />
        )}
      </div>
      <div className="workbench" ref={workbench}>
        <ProjectSidebar
          onCollapse={toggleSidebar}
          sortedSidebar={sortedSidebar}
          sidebarSort={sidebarSort}
          onSortChange={setSidebarSort}
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
            /* 新建会话后更新工作台状态 */ (id) =>
              run(() => newConversation(id))
          }
          onArchive={
            /* 处理 onArchive 回调，将变化同步到工作台状态 */ (projectId, id) =>
              run(() => archiveConversation(projectId, id))
          }
          onDelete={setDeletingProject}
          onImport={
            /* 处理 onImport 回调，将变化同步到工作台状态 */ () =>
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
          onChange={(value) => resize("sidebar", value)}
          onReset={() => resize("sidebar", DEFAULT_LAYOUT.sidebar)}
        />
        <main className="workspace">
          {!loaded ? (
            <div className="empty">
              <LoaderCircle className="spin" />
              正在读取本机数据…
            </div>
          ) : area === "personal" ? (
            <ProfileEditor
              honors={state.honors ?? []}
              onEditHonor={editLinkedHonor}
              key={draft.id}
              value={draft.document ?? newDocument(state.resume_defaults)}
              savedPersonal={
                state.resumes.find(
                  /* 读取正式保存的基本信息以区分待保存草稿 */ (resume) =>
                    resume.id === draft.id,
                )?.document?.personal
              }
              savedVersion={
                state.resumes.find(
                  /* 成功保存组合也应结束当前基本信息的编辑会话 */ (resume) =>
                    resume.id === draft.id,
                )?.version
              }
              onSave={savePersonalInfo}
              onSaveEntry={saveSectionEntry}
              savedSections={
                state.resumes.find(
                  /* 各条资料和该方案的已保存内容独立比较 */ (resume) =>
                    resume.id === draft.id,
                )?.document?.sections
              }
              onChange={
                /* 完整模板随资料编辑保留，项目区模板切换为内置版式 */ (
                  document,
                ) =>
                  setDraft(
                    /* 使用最新方案以免照片读取期间覆盖其他设置 */ (
                      current,
                    ) => ({
                      ...current,
                      document,
                    }),
                  )
              }
              onStructure={
                /* 从资料编辑进入栏目编排 */ () => setArea("structure")
              }
              onProjects={/* 返回项目工作台 */ () => setArea("projects")}
              onHonors={
                /* 添加证书进入荣誉库，保留当前简历草稿 */ () =>
                  setArea("honors")
              }
              onSortSection={
                /* 在编排页定位刚才查看的栏目 */ (sectionId) => {
                  setStructureTarget(sectionId);
                  setArea("structure");
                }
              }
            />
          ) : area === "structure" ? (
            <SectionOrganizer
              onDefaults={/* 打开独立设置副本 */ () => setDefaultsOpen(true)}
              honors={state.honors ?? []}
              scrollTarget={structureTarget}
              onScrolled={
                /* 消费一次定位请求，普通切换不重复跳动 */ () =>
                  setStructureTarget(null)
              }
              key={draft.id}
              value={draft.document ?? newDocument(state.resume_defaults)}
              onEditHonor={
                /* 关联来源读取最新资料，手动条目只编辑当前简历 */ (
                  sectionId,
                  entry,
                ) =>
                  void editLinkedHonor(
                    entry.id.startsWith("honor:") &&
                      !entry.id.startsWith("honor:manual:")
                      ? entry.id.slice("honor:".length)
                      : "",
                    sectionId,
                    entry,
                  )
              }
              projects={
                <ProjectOrder
                  draft={draft}
                  revisions={revisionCache}
                  sources={previewSources}
                  onChange={setDraft}
                  onEdit={
                    /* 从栏目内选中项目并返回其经历编辑区 */ (id) =>
                      followGuide("experience-use", id)
                  }
                />
              }
              onChange={
                /* 栏目结构和个人资料共用当前完整模板 */ (document) =>
                  setDraft(
                    /* 保留栏目编辑期间的其他简历设置 */ (current) => ({
                      ...current,
                      document,
                    }),
                  )
              }
              onInfo={/* 返回资料编辑 */ () => setArea("personal")}
            />
          ) : !project ? (
            <div className="empty welcome">
              <span className="eyebrow">从你的项目开始</span>
              <h1>把项目积累，变成可复用的经历。</h1>
              <p>
                导入源码目录，让 Codex
                提取项目事实；编辑每条亮点，再组合成简历。
              </p>
              <button className="primary" onClick={() => setModal("projects")}>
                <FolderPlus size={17} />
                导入项目集合
              </button>
            </div>
          ) : (
            <>
              <header className="workspace-header">
                <div>
                  {parentProject ? (
                    <button
                      className="project-parent-link"
                      title={`返回整体项目 ${parentProject.name}`}
                      onClick={
                        /* 返回原有整体项目经历和对话 */ () =>
                          navigate(parentProject.id)
                      }
                    >
                      {parentProject.name} / 子项目
                    </button>
                  ) : project.roots.length > 1 ? (
                    <span className="project-scope-hint">
                      整体项目 · {project.roots.length} 个子项目
                    </span>
                  ) : null}
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
                    onClick={() => run(async () => setMode("edit"))}
                  >
                    <FilePenLine size={14} aria-hidden="true" />
                    经历编辑
                  </button>
                  <button
                    className={mode === "chat" ? "active" : ""}
                    aria-current={mode === "chat" ? "page" : undefined}
                    onClick={() =>
                      run(async () => {
                        await ensureConversation();
                        setMode("chat");
                      })
                    }
                  >
                    <Sparkles size={14} aria-hidden="true" />
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
                  onClick={() =>
                    run(() =>
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
                      definitions={
                        draft.document?.sections.find(
                          /* 当前简历保留独立项目字段结构 */ (section) =>
                            section.kind === "projects",
                        )?.field_definitions
                      }
                      key={`${activeProject}.${revisionId}.${refresh}`}
                      detail={remoteProject.data}
                      revisionId={revisionId}
                      hasLocalChanges={hasExperienceChanges}
                      usedRevision={
                        revisionCache[
                          draft.items.find(
                            (item) => item.project_id === activeProject,
                          )?.revision_id ?? ""
                        ]
                      }
                      included={
                        draft.items.find((i) => i.project_id === activeProject)
                          ?.highlight_ids ?? []
                      }
                      visibility={
                        draft.document?.project_visibility?.[activeProject] ??
                        {}
                      }
                      onVisibility={changeProjectVisibility}
                      run={run}
                      onSave={saveRevision}
                      onDiscard={discardChanges}
                      onRefresh={changed}
                      onRevision={
                        /* 处理 onRevision 回调，将变化同步到工作台状态 */ (
                          id,
                        ) =>
                          run(async () =>
                            setSelectedRevisions((v) => ({
                              ...v,
                              [activeProject]: id,
                            })),
                          )
                      }
                      onUseVersion={applyVersion}
                      onAsk={ask}
                      onToggle={toggleHighlight}
                      onPreview={updateWorkingPreview}
                    />
                  ) : (
                    <div className="empty compact">正在读取草稿…</div>
                  )
                ) : remoteChat.data ? (
                  <Chat
                    key={conversationId}
                    inputHeight={layout.chatInput}
                    onInputHeight={
                      /* 处理 onInputHeight 回调，将变化同步到工作台状态 */ (
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
          onChange={(value) => resize("composer", value)}
          onReset={() => resize("composer", DEFAULT_LAYOUT.composer)}
        />
        <ResizeHandle
          className="stack-resize"
          label="调整编辑区高度"
          axis="y"
          value={clamp(layout.editor, 280, 1000)}
          min={280}
          max={1000}
          onChange={(value) => resize("editor", value)}
          onReset={() => resize("editor", DEFAULT_LAYOUT.editor)}
        />
        <Composer
          previewFocused={previewFocused}
          onFocusPreview={
            /* 切换右侧预览的放大状态 */ () =>
              setPreviewFocused(!previewFocused)
          }
          state={state}
          draft={draft}
          revisions={revisionCache}
          previewSources={previewSources}
          run={run}
        />
      </div>
      {resumeLibraryOpen && (
        <ResumeLibrary
          notice={toast}
          onDismissNotice={/* 在模态层内清除操作提示 */ () => setToast(null)}
          state={state}
          draft={draft}
          previewChanged={previewChanged}
          result={exported}
          exporting={exporting}
          deleting={deleting}
          onClose={
            /* 关闭简历库，保留当前方案和所有本机草稿 */ () =>
              setResumeLibraryOpen(false)
          }
          onChange={setDraft}
          onChoose={
            /* 处理 onChoose 回调，将变化同步到工作台状态 */ (id) =>
              run(async () => {
                const resume = state.resumes.find((r) => r.id === id);
                if (resume) {
                  setDraft(loadLocal(`rm.resume.v2.${id}`, resume));
                  setExported(null);
                }
              })
          }
          onSave={
            /* 处理 onSave 回调，将变化同步到工作台状态 */ () =>
              run(async () => {
                await saveComposition();
                setToast({ text: "简历组合已保存，引用版本已固定。" });
              })
          }
          onExport={
            /* 处理 onExport 回调，将变化同步到工作台状态 */ () =>
              run(exportResume)
          }
          onNew={
            /* 处理 onNew 回调，将变化同步到工作台状态 */ () =>
              run(async () => {
                const value = await api<Resume>("/resumes", "POST", {
                  name: "新简历",
                  template_id: null,
                  items: [],
                  document: newDocument(state.resume_defaults),
                });
                await reload();
                setDraft(value);
                setExported(null);
              })
          }
          onDelete={
            /* 先刷新项目草稿，再删除用户确认的方案 */ (resume) =>
              run(/* 执行方案删除及后续切换 */ () => deleteComposition(resume))
          }
          onTemplates={
            /* 处理 onTemplates 回调，将变化同步到工作台状态 */ () =>
              run(
                /* 保存草稿后打开完整模板工作区 */ async () => {
                  setResumeLibraryOpen(false);
                  setArea("templates");
                  setPreviewFocused(false);
                },
              )
          }
        />
      )}
      <HonorLibrary
        onSaved={honorSaved}
        active={area === "honors"}
        document={draft.document}
        resumeName={draft.name}
        onRemove={
          /* 荣誉库移除入口只更新当前草稿，保留来源和其他简历 */ (id) =>
            setDraft(
              /* 使用最新草稿以免覆盖其他未保存设置 */ (current) => ({
                ...current,
                document: current.document
                  ? removeHonor(current.document, id)
                  : current.document,
              }),
            )
        }
        onAdd={
          /* 将已确认的荣誉复制到当前简历草稿，保留其他资料 */ (
            honors,
            target,
          ) => {
            const document = addHonors(
              draft.document ?? newDocument(state.resume_defaults),
              honors,
              target,
            );
            setDraft({ ...draft, document });
          }
        }
      />
      {defaultsOpen && (
        <DefaultsDialog
          document={draft.document}
          projects={[
            ...Object.values(revisionCache).map(
              /* 不改写不可变版本且只用于判断是否需要删除确认 */ (revision) =>
                revision.content,
            ),
            ...Object.values(workingPreviews),
            ...(remoteProject.data ? [remoteProject.data.working.content] : []),
          ]}
          initial={state.resume_defaults}
          onClose={/* 关闭设置不修改资料 */ () => setDefaultsOpen(false)}
          onSave={
            /* 先校验应用结果，再保存默认设置并更新当前草稿 */ async (
              settings,
            ) => {
              const document = applyResumeDefaults(
                draft.document ?? newDocument(),
                settings,
                state.resume_defaults ?? undefined,
              );
              const saved = await api<ResumeDefaults>(
                "/settings/resume-defaults",
                "PUT",
                settings,
              );
              ++stateRequests.current;
              setState(
                /* 使新建简历立即使用新设置 */ (current) => ({
                  ...current,
                  resume_defaults: saved,
                }),
              );
              setDraft(
                /* 模态期间保留当前简历其他元信息 */ (current) => ({
                  ...current,
                  document,
                }),
              );
            }
          }
        />
      )}
      {editingHonor && (
        <HonorEditor
          key={`${editingHonor.resumeId}:${editingHonor.entry.id}`}
          honor={editingHonor.honor}
          resumeEntry={editingHonor.entry}
          onSaveEntry={
            /* 只提交当前荣誉条目的草稿 */ async (entry) => {
              if (draft.id !== editingHonor.resumeId)
                throw new Error("当前简历已切换，请关闭后重新编辑。");
              await saveSectionEntry(editingHonor.sectionId, entry.id, entry);
            }
          }
          onClose={
            /* 关闭共享荣誉表单后返回当前资料位置 */ () => setEditingHonor(null)
          }
          onSaved={
            /* 来源成功而简历保存失败时，表单继续使用已确认的新版本重试 */ (
              honor,
            ) => {
              honorSaved(honor);
              setEditingHonor(
                /* 保留本次简历设置和打开时的取消基线 */ (current) =>
                  current?.honor?.id === honor.id
                    ? { ...current, honor }
                    : current,
              );
            }
          }
        />
      )}
      <div
        className="template-workspace"
        hidden={area !== "templates"}
        data-guide="template-select"
        tabIndex={-1}
      >
        <TemplateAdapter
          active={area === "templates"}
          layout={layout}
          onResize={resize}
          resume={draft}
          revisions={revisionCache}
          previewSources={previewSources}
          onSelected={
            /* 将已确认的完整模板用于当前草稿 */ (id) =>
              setDraft(
                /* 采用新模板时保留全部个人资料和项目选择 */ (current) => ({
                  ...current,
                  template_id: id,
                  document:
                    current.document ?? newDocument(state.resume_defaults),
                }),
              )
          }
          templates={state.templates}
          onChanged={
            /* 保存模板后刷新模板库 */ async () => {
              await reload();
              changed();
            }
          }
        />
      </div>
      {deletingProject && (
        <DeleteProjectDialog
          project={deletingProject}
          childCount={deletingProjectIds.size - 1}
          blocker={deletionBlocker}
          onClose={() => setDeletingProject(null)}
          onDelete={deleteProject}
        />
      )}
      {modal && (
        <Settings
          initial={modal}
          onClose={
            /* 处理 onClose 回调，将变化同步到工作台状态 */ () => setModal(null)
          }
          onChanged={
            /* 处理 onChanged 回调，将变化同步到工作台状态 */ async () => {
              await reload();
              changed();
            }
          }
          run={run}
        />
      )}
      {toast && !resumeLibraryOpen && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          <span>{toast.text}</span>
          <button
            className="icon-button"
            aria-label="关闭提示"
            onClick={() => setToast(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
