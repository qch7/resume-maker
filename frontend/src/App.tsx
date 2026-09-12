import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FolderPlus,
  LoaderCircle,
  MessageSquarePlus,
  MoreHorizontal,
  PanelLeftClose,
  RefreshCw,
  Settings as SettingsIcon,
  Sparkles,
  X,
} from "lucide-react";
import { api, loadLocal } from "./api";
import { clearLocalDrafts, flushDrafts } from "./drafts";
import Chat from "./Chat";
import Composer from "./Composer";
import Editor from "./Editor";
import Settings from "./Settings";
import ThemeSwitch from "./ThemeSwitch";
import Workflow from "./Workflow";
import { getWorkflow, type GuideTarget } from "./workflowState";
import type {
  Conversation,
  ConversationDetail,
  Export,
  ProjectDetail,
  Proposal,
  Resume,
  Revision,
  State,
} from "./types";

const EMPTY: State = {
  projects: [],
  conversations: [],
  resumes: [],
  templates: [],
  jobs: [],
};
const NEW_RESUME: Resume = {
  id: "",
  name: "我的简历",
  template_id: null,
  items: [],
  version: 0,
};

function useRemote<T>(path: string | null, refresh: number) {
  const [result, setResult] = useState<{
    path: string;
    refresh: number;
    value: T;
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setError("");
    void api<T>(path, "GET", undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setResult({ path, refresh, value });
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [path, refresh]);
  return {
    data: result?.path === path ? result.value : null,
    ready: result?.path === path && result.refresh === refresh,
    error,
  };
}

export default function App() {
  const [state, setState] = useState<State>(EMPTY),
    [loaded, setLoaded] = useState(false);
  const [activeProject, setActiveProject] = useState("");
  const [selectedRevisions, setSelectedRevisions] = useState<
    Record<string, string>
  >({});
  const [selectedConversations, setSelectedConversations] = useState<
    Record<string, string>
  >({});
  const [mode, setMode] = useState<"edit" | "chat">("edit");
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  const [sidebar, setSidebar] = useState(
    () => !matchMedia("(max-width: 600px)").matches,
  );
  const [edited, setEdited] = useState<Record<string, boolean>>({});
  const [guideTarget, setGuideTarget] = useState<GuideTarget | null>(null);
  const [modal, setModal] = useState<
    "projects" | "templates" | "settings" | null
  >(null);
  const [refresh, setRefresh] = useState(0),
    [toast, setToast] = useState<{ text: string; error?: boolean } | null>(
      null,
    );
  const [draft, setDraft] = useState<Resume>(() =>
    loadLocal("rm.resume.last", NEW_RESUME),
  );
  const [revisionCache, setRevisionCache] = useState<Record<string, Revision>>(
    {},
  );
  const [exported, setExported] = useState<Export | null>(null),
    [exporting, setExporting] = useState(false);
  useEffect(() => {
    if (!draft.id) {
      setExported(null);
      return;
    }
    const controller = new AbortController();
    void api<Export[]>(
      `/resumes/${draft.id}/exports`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((rows) => {
        if (!controller.signal.aborted)
          setExported((previous) =>
            previous?.resume_id === draft.id &&
            previous.created_at > (rows[0]?.created_at ?? "")
              ? previous
              : (rows[0] ?? null),
          );
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setToast({ text: error.message, error: true });
      });
    return () => controller.abort();
  }, [draft.id]);
  const initialized = useRef(false),
    navigation = useRef(0);
  const project = state.projects.find((p) => p.id === activeProject);
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

  const reload = useCallback(async () => {
    const value = await api<State>("/state");
    setState(value);
    setLoaded(true);
    if (!initialized.current) {
      initialized.current = true;
      const cached = loadLocal<Resume>("rm.resume.last", NEW_RESUME);
      const valid =
        cached.items.every((item) =>
          value.projects.some((p) => p.id === item.project_id),
        ) &&
        (!cached.id || value.resumes.some((r) => r.id === cached.id));
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

  useEffect(() => {
    let stopped = false,
      timer: ReturnType<typeof setTimeout>;
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
  useEffect(() => {
    if (!activeProject && state.projects[0]) {
      setActiveProject(state.projects[0].id);
      setSelectedRevisions((v) => ({
        ...v,
        [state.projects[0].id]: state.projects[0].head_revision,
      }));
    }
  }, [activeProject, state.projects]);
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
        .catch((e) => setToast({ text: e.message, error: true }));
  }, [draft.items, revisionCache]);
  useEffect(() => {
    localStorage.setItem("rm.resume.last", JSON.stringify(draft));
    localStorage.setItem(
      `rm.resume.${draft.id || "new"}`,
      JSON.stringify(draft),
    );
  }, [draft]);
  useEffect(() => {
    if (!toast || toast.error) return;
    const timer = setTimeout(() => setToast(null), 4500);
    return () => clearTimeout(timer);
  }, [toast]);

  function run(work: () => Promise<void>) {
    void (async () => {
      try {
        await flushDrafts();
        await work();
      } catch (error) {
        setToast({ text: (error as Error).message, error: true });
      }
    })();
  }
  function changed() {
    setEdited((value) => ({
      ...value,
      [`${activeProject}.${revisionId}`]: false,
    }));
    setRefresh((v) => v + 1);
    void reload();
  }
  function navigate(projectId: string, convId?: string) {
    const serial = ++navigation.current;
    run(async () => {
      if (serial !== navigation.current) return;
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
        setSelectedConversations((v) => ({ ...v, [projectId]: convId }));
      setFolded((v) => ({ ...v, [projectId]: false }));
    });
  }
  async function newConversation() {
    if (!activeProject) return;
    const conv = await api<Conversation>(
      `/projects/${activeProject}/conversations`,
      "POST",
    );
    await reload();
    setSelectedConversations((v) => ({ ...v, [activeProject]: conv.id }));
    setMode("chat");
    setFolded((v) => ({ ...v, [activeProject]: false }));
    changed();
  }
  async function ensureConversation() {
    if (conversationId) return conversationId;
    const conv = await api<Conversation>(
      `/projects/${activeProject}/conversations`,
      "POST",
    );
    setSelectedConversations((v) => ({ ...v, [activeProject]: conv.id }));
    await reload();
    return conv.id;
  }
  async function ask(scope: string) {
    const id = await ensureConversation();
    await api(`/conversations/${id}`, "PATCH", { scope });
    setMode("chat");
    changed();
  }
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
    setSelectedRevisions((v) => ({ ...v, [activeProject]: result.id }));
    setRevisionCache((v) => ({ ...v, [result.id]: result }));
    changed();
    setToast({
      text:
        result.id === revisionId
          ? "没有需要保存的新修改。"
          : `已保存为 r${result.number}。点击“用于当前简历”可更新右侧组合。`,
    });
  }
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
  function useVersion() {
    const revision = revisionCache[revisionId];
    if (!revision) return;
    const previous = draft.items.find((i) => i.project_id === activeProject);
    const validIds = revision.content.highlights.map((h) => h.id);
    const hadHighlights =
      previous &&
      revisionCache[previous.revision_id]?.content.highlights.length;
    const item = {
      project_id: activeProject,
      revision_id: revisionId,
      highlight_ids:
        previous && hadHighlights
          ? previous.highlight_ids.filter((id) => validIds.includes(id))
          : validIds,
    };
    setDraft({
      ...draft,
      items: previous
        ? draft.items.map((i) => (i.project_id === activeProject ? item : i))
        : [...draft.items, item],
    });
  }
  function toggleProject(id: string) {
    run(async () => {
      if (draft.items.some((i) => i.project_id === id)) {
        setDraft((value) => ({
          ...value,
          items: value.items.filter((i) => i.project_id !== id),
        }));
        return;
      }
      const head = state.projects.find((p) => p.id === id)!.head_revision;
      const revision =
        revisionCache[head] ?? (await api<Revision>(`/revisions/${head}`));
      setRevisionCache((v) => ({ ...v, [head]: revision }));
      setDraft((value) =>
        value.items.some((i) => i.project_id === id)
          ? value
          : {
              ...value,
              items: [
                ...value.items,
                {
                  project_id: id,
                  revision_id: head,
                  highlight_ids: revision.content.highlights.map((h) => h.id),
                },
              ],
            },
      );
    });
  }
  function toggleHighlight(id: string) {
    const current = draft.items.find((i) => i.project_id === activeProject);
    if (!current) {
      setToast({ text: "请先将该经历版本用于当前简历。" });
      return;
    }
    if (
      !revisionCache[current.revision_id]?.content.highlights.some(
        (h) => h.id === id,
      )
    ) {
      setToast({
        text: "这条亮点尚未保存在简历引用的版本中，请先保存并更新组合。",
      });
      return;
    }
    setDraft({
      ...draft,
      items: draft.items.map((i) =>
        i.project_id === activeProject
          ? {
              ...i,
              highlight_ids: i.highlight_ids.includes(id)
                ? i.highlight_ids.filter((x) => x !== id)
                : [...i.highlight_ids, id],
            }
          : i,
      ),
    });
  }
  async function saveComposition() {
    const body = {
      name: draft.name,
      template_id: draft.template_id,
      items: draft.items,
      version: draft.version,
    };
    const saved = await api<Resume>(
      draft.id ? `/resumes/${draft.id}` : "/resumes",
      draft.id ? "PUT" : "POST",
      body,
    );
    setDraft(saved);
    await reload();
    return saved;
  }
  async function exportResume() {
    setExporting(true);
    try {
      const saved = await saveComposition();
      const result = await api<Export>(`/resumes/${saved.id}/exports`, "POST");
      setExported(result);
      setToast({
        text: result.pages
          ? `Word 已生成，共 ${result.pages} 页。`
          : "Word 已生成，可下载；渲染结果见右侧。",
      });
    } finally {
      setExporting(false);
    }
  }
  function followGuide(target: GuideTarget, projectId?: string) {
    if (target === "projects" || !project) {
      setModal("projects");
      return;
    }
    if (target === "template-select" && !state.templates.length) {
      setModal("templates");
      return;
    }
    run(async () => {
      if (projectId) {
        const next = state.projects.find((p) => p.id === projectId);
        if (!next) return;
        setActiveProject(projectId);
        setSelectedRevisions((value) => ({
          ...value,
          [projectId]: next.head_revision,
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
  }, [guideTarget, mode, remoteProject.ready, activeProject]);
  const workflow = getWorkflow({
    projectCount: state.projects.length,
    detail: remoteProject.ready ? remoteProject.data : null,
    revisionId,
    edited: !!edited[`${activeProject}.${revisionId}`],
    draft,
    saved: state.resumes.find((r) => r.id === draft.id),
    revisions: revisionCache,
    result: exported,
    exporting,
    analyzing: !!currentJob,
  });
  const error = remoteProject.error || remoteChat.error;
  return (
    <div className={`app-shell ${sidebar ? "" : "sidebar-hidden"}`}>
      <header className="app-header">
        <div className="row">
          <button
            className="icon-button"
            aria-label="切换侧边栏"
            onClick={() => setSidebar(!sidebar)}
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
      <Workflow value={workflow} onNavigate={followGuide} />
      <aside className="sidebar">
        <button
          className="new-chat"
          disabled={!project}
          onClick={() => run(newConversation)}
        >
          <MessageSquarePlus size={18} />
          新会话
        </button>
        <span className="sidebar-caption">
          {project ? `当前项目：${project.name}` : "先导入项目集合"}
        </span>
        <nav className="project-navigation" aria-label="项目与会话">
          {state.projects.map((p) => (
            <section className="project-group" key={p.id}>
              <div
                className={`project-row ${activeProject === p.id && mode === "edit" ? "selected" : ""}`}
              >
                <input
                  type="checkbox"
                  aria-label={`将 ${p.name} 加入简历`}
                  checked={draft.items.some((i) => i.project_id === p.id)}
                  onChange={() => toggleProject(p.id)}
                />
                <button className="project-name" onClick={() => navigate(p.id)}>
                  {p.name}
                </button>
                <button
                  className="icon-button"
                  aria-label={`${folded[p.id] ? "展开" : "收起"} ${p.name} 会话`}
                  aria-expanded={!folded[p.id]}
                  onClick={() => setFolded((v) => ({ ...v, [p.id]: !v[p.id] }))}
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
                  {state.conversations
                    .filter((c) => c.project_id === p.id)
                    .map((c) => (
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
                          onClick={() => navigate(p.id, c.id)}
                        >
                          {c.title}
                          {activeJobs.some(
                            (j) => j.conversation_id === c.id,
                          ) && <span className="activity-dot" />}
                        </button>
                        <details className="session-menu">
                          <summary aria-label={`管理会话 ${c.title}`}>
                            <MoreHorizontal size={15} />
                          </summary>
                          <div>
                            <button
                              onClick={() =>
                                run(async () => {
                                  await api(`/conversations/${c.id}`, "PATCH", {
                                    archived: true,
                                  });
                                  if (selectedConversations[p.id] === c.id)
                                    setSelectedConversations((v) => {
                                      const next = { ...v };
                                      delete next[p.id];
                                      return next;
                                    });
                                  changed();
                                })
                              }
                            >
                              归档会话
                            </button>
                          </div>
                        </details>
                      </div>
                    ))}
                </div>
              )}
            </section>
          ))}
        </nav>
        <button className="sidebar-footer" onClick={() => setModal("projects")}>
          <FolderPlus size={17} />
          导入项目
        </button>
      </aside>
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
              导入源码目录，让 Codex 提取项目事实；编辑每条亮点，再组合成简历。
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
                <span className="eyebrow">{project.name}</span>
                <h1>
                  {remoteProject.data?.working.content.title || project.name}
                </h1>
              </div>
              <button
                data-guide="analysis"
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
                {remoteProject.data?.working.content.highlights.length
                  ? "重新分析源码"
                  : "分析项目"}
              </button>
            </header>
            <nav className="tabs workspace-tabs">
              <button
                className={mode === "edit" ? "active" : ""}
                onClick={() => run(async () => setMode("edit"))}
              >
                经历编辑
              </button>
              <button
                className={mode === "chat" ? "active" : ""}
                onClick={() =>
                  run(async () => {
                    await ensureConversation();
                    setMode("chat");
                  })
                }
              >
                AI 会话
              </button>
            </nav>
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
                    hasLocalChanges={!!edited[`${activeProject}.${revisionId}`]}
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
                    run={run}
                    onSave={saveField}
                    onRefresh={changed}
                    onDirty={() =>
                      setEdited((value) => ({
                        ...value,
                        [`${activeProject}.${revisionId}`]: true,
                      }))
                    }
                    onRevision={(id) =>
                      run(async () =>
                        setSelectedRevisions((v) => ({
                          ...v,
                          [activeProject]: id,
                        })),
                      )
                    }
                    onUseVersion={useVersion}
                    onAsk={ask}
                    onToggle={toggleHighlight}
                  />
                ) : (
                  <div className="empty compact">正在读取草稿…</div>
                )
              ) : remoteChat.data ? (
                <Chat
                  key={conversationId}
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
      <Composer
        state={state}
        draft={draft}
        revisions={revisionCache}
        result={exported}
        exporting={exporting}
        onChange={setDraft}
        onChoose={(id) =>
          run(async () => {
            const resume = state.resumes.find((r) => r.id === id);
            if (resume) {
              setDraft(loadLocal(`rm.resume.${id}`, resume));
              setExported(null);
            }
          })
        }
        onSave={() =>
          run(async () => {
            await saveComposition();
            setToast({ text: "简历组合已保存，引用版本已固定。" });
          })
        }
        onExport={() => run(exportResume)}
        onNew={() =>
          run(async () => {
            const value = await api<Resume>("/resumes", "POST", {
              name: "新简历",
              template_id: state.templates[0]?.id ?? null,
              items: [],
            });
            await reload();
            setDraft(value);
            setExported(null);
          })
        }
        onTemplates={() => setModal("templates")}
        onEditProject={(id) => followGuide("experience-use", id)}
        run={run}
      />
      {modal && (
        <Settings
          initial={modal}
          onClose={() => setModal(null)}
          onChanged={async () => {
            await reload();
            changed();
          }}
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
            onClick={() => setToast(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
