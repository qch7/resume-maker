import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { FileScan, LoaderCircle, Sparkles } from "lucide-react";
import PathInput from "../../shared/components/PathInput";
import ResizeHandle from "../../shared/components/ResizeHandle";
import TemplateOptions from "../../shared/components/TemplateOptions";
import { useElementSize } from "../../shared/hooks/useElementSize";
import {
  DEFAULT_LAYOUT,
  templateSizes,
  type Layout,
} from "../../shared/lib/layout";
import { api, ApiError, download } from "../../shared/lib/api";
import type { Resume, Revision, Template } from "../../shared/types";
import { newDocument } from "../profile/document";
import PrintedPage from "../resumes/PrintedPage";
import TemplateProgress from "./TemplateProgress";
import RecognitionSummary from "./RecognitionSummary";
import AdvancedMapping from "./AdvancedMapping";
import BuiltinTemplate from "./BuiltinTemplate";
import TemplateCanvas from "./TemplateCanvas";
import TemplateInspector from "./TemplateInspector";
import { REGION_LABELS, siblingRange } from "./visual";
import { reviewProblems, reviewProblemSummary } from "./review";
import type {
  MappingReview,
  TemplateAnalysis,
  TemplatePlan,
  TemplateProgressData,
} from "./types";

type Preview = {
  id: string;
  pages: number | null;
  render_error: string | null;
};

/** 在独立工作区识别、可视化调整、试填和保存完整 Word 模板。 */
export default function TemplateAdapter({
  active,
  layout,
  onResize,
  resume,
  revisions,
  previewSources,
  templates,
  onChanged,
  onSelected,
}: {
  active: boolean;
  layout: Layout;
  onResize: (key: keyof Layout, value: number | boolean) => void;
  resume: Resume;
  revisions: Record<string, Revision>;
  previewSources: Record<string, Revision>;
  templates: Template[];
  onChanged: () => Promise<void>;
  onSelected: (id: string | null) => void;
}) {
  const workspace = useRef<HTMLElement>(null);
  const size = useElementSize(workspace);
  const sizes = templateSizes(size.width, size.height, layout);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [libraryId, setLibraryId] = useState<string | null>(
    /* 未显式选择时跟随当前简历，空字符串明确表示内置版式。 */ () =>
      sessionStorage.getItem("rm.template.library"),
  );
  const [taskId, setTaskId] = useState(
    /* 恢复同一服务实例中尚未确认的分析。 */ () =>
      sessionStorage.getItem("rm.template.analysis") ?? "",
  );
  const [analysis, setAnalysis] = useState<TemplateAnalysis | null>(null);
  const [plan, setPlan] = useState<TemplatePlan | null>(null);
  const [review, setReview] = useState<MappingReview | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [rangeAnchor, setRangeAnchor] = useState<string | null>(null);
  const [view, setView] = useState<"summary" | "structure" | "preview">(
    "summary",
  );
  const [filter, setFilter] = useState<"all" | "unresolved">("all");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [openedId, setOpenedId] = useState(libraryId);
  const [notice, setNotice] = useState("");
  const [importError, setImportError] = useState<{
    fileName: string;
    message: string;
  } | null>(null);
  const [feedback, setFeedback] = useState("");
  const autoPreview = useRef(true);
  const document = useMemo(
    /* 空白简历也保持资料对象稳定，避免异步响应被误判为过期。 */ () =>
      resume.document ?? newDocument(),
    [resume.document],
  );
  const latest = useRef({
    taskId,
    plan,
    document,
    items: resume.items,
    resumeId: resume.id,
  });
  latest.current = {
    taskId,
    plan,
    document,
    items: resume.items,
    resumeId: resume.id,
  };
  const running = analysis?.status === "running";
  const problems = reviewProblems(review);
  const problemSummary = reviewProblemSummary(problems);
  const trialDisabledReason =
    busy || running
      ? "正在处理，请稍候"
      : !review
        ? "正在自动检查模板"
        : !review.ready
          ? `暂不可用：${problemSummary}`
          : "";
  const saveDisabledReason =
    trialDisabledReason ||
    (!name.trim()
      ? "请先填写模板名称"
      : !preview
        ? "请先生成试填预览，核对后即可保存"
        : "");
  const nodes = analysis?.inventory.nodes ?? [];
  const savedId = libraryId ?? resume.template_id ?? "";
  const builtin = savedId === "" && !taskId;
  const saved = templates.find(
    /* 定位模板库中当前选项。 */ (item) => item.id === savedId,
  );
  // 恢复中的分析优先保留；显式选模板时才替换，避免覆盖尚未保存的识别。
  const requestedId = useRef(taskId ? savedId : "");
  const libraryRequest = useRef<AbortController | null>(null);
  const selectionVersion = useRef(0);
  const selection = selectionVersion.current;
  const viewedResume = useRef<string | null>(null);
  useEffect(
    /* 新进入的简历默认显示其实际版式；同一简历切换栏目不重置模板编辑。 */ () => {
      if (!active) return;
      const key = JSON.stringify([resume.id, resume.template_id]);
      if (viewedResume.current !== key) {
        const restoringImport =
          viewedResume.current === null && taskId && !libraryId;
        viewedResume.current = key;
        if (
          !restoringImport &&
          !running &&
          savedId !== (resume.template_id ?? "")
        ) {
          void loadSaved(resume.template_id ?? "");
          return;
        }
      }
      if (active && saved && requestedId.current !== saved.id)
        void loadSaved(saved.id);
    },
    [active, saved?.id, savedId, taskId, resume.id, resume.template_id],
  );
  useEffect(
    /* 请求跨栏目切换保留，只在卸载或选择另一模板时取消映射读取。 */ () =>
      /* 卸载后所有映射及试填结果均不再更新界面。 */ () => {
        libraryRequest.current?.abort();
        selectionVersion.current++;
      },
    [],
  );
  useEffect(
    /* 资料变化后旧试填不再代表当前简历，必须重新生成。 */ () => {
      setPreview(null);
      setView("summary");
    },
    [resume.document, resume.items, resume.id],
  );
  useEffect(
    /* 首次及完成时加载结果，运行中只拉增量活动；重连不丢失任务。 */ () => {
      if (!taskId) return;
      const controller = new AbortController();
      let timer: ReturnType<typeof setTimeout>;
      let loaded = false;
      let cursor = 0;
      /** 响应后才安排下一轮，结束后不再覆盖用户的人工调整。 */
      async function poll() {
        try {
          if (loaded) {
            const progress = await api<TemplateProgressData>(
              `/templates/analyses/${taskId}/progress?after=${cursor}`,
              "GET",
              undefined,
              controller.signal,
            );
            if (
              controller.signal.aborted ||
              selectionVersion.current !== selection
            )
              return;
            setNotice(
              /* 重连成功只清除连接提示，保留其他操作反馈。 */ (previous) =>
                previous === "实时动态连接中断，正在重新连接…" ? "" : previous,
            );
            cursor = progress.cursor;
            setAnalysis(
              /* 合并增量活动，保留已加载的清单和方案。 */ (previous) =>
                previous?.id === taskId
                  ? {
                      ...previous,
                      ...progress,
                      events: [...previous.events, ...progress.events].slice(
                        -80,
                      ),
                    }
                  : previous,
            );
            if (progress.status === "running") {
              timer = setTimeout(poll, 800);
              return;
            }
          }
          const value = await api<TemplateAnalysis>(
            `/templates/analyses/${taskId}`,
            "GET",
            undefined,
            controller.signal,
          );
          loaded = true;
          cursor = value.cursor;
          if (
            controller.signal.aborted ||
            selectionVersion.current !== selection
          )
            return;
          setAnalysis(value);
          if (value.status === "running") timer = setTimeout(poll, 800);
          else {
            setPlan(value.plan);
            setReview(value.review);
            setName(
              value.file_name.replace(/\.(docx?|docm|rtf|pdf|png|jpe?g)$/i, ""),
            );
            setSelected(
              value.plan?.fields[0] ? [value.plan.fields[0].node] : [],
            );
            if (value.error) setNotice(value.error);
          }
        } catch (error) {
          if (
            !controller.signal.aborted &&
            selectionVersion.current === selection
          ) {
            if (
              error instanceof ApiError &&
              [401, 404].includes(error.status)
            ) {
              setNotice(error.message);
              setAnalysis(
                /* 服务重启或鉴权失效后结束旧进度展示。 */ (previous) =>
                  previous
                    ? { ...previous, status: "failed", activity: error.message }
                    : previous,
              );
              sessionStorage.removeItem("rm.template.analysis");
              if (error.status === 404) {
                requestedId.current = "";
                setTaskId("");
              }
            } else {
              setNotice("实时动态连接中断，正在重新连接…");
              timer = setTimeout(poll, 2000);
            }
          }
        }
      }
      void poll();
      return /* 任务切换或页面卸载后丢弃迟到结果。 */ () => {
        controller.abort();
        clearTimeout(timer);
      };
    },
    [taskId],
  );
  useEffect(
    /* 每次调整后自动校验当前方案，取消旧请求以免覆盖较新的修改。 */ () => {
      if (!plan || !taskId || running) return;
      const controller = new AbortController();
      const timer = setTimeout(
        /* 等待连续编辑结束再校验。 */ async () => {
          try {
            const value = await api<MappingReview>(
              `/templates/analyses/${taskId}/review`,
              "POST",
              { plan, document, items: resume.items },
              controller.signal,
            );
            if (!controller.signal.aborted && isCurrent()) setReview(value);
          } catch (error) {
            if (!controller.signal.aborted && isCurrent())
              setNotice((error as Error).message);
          }
        },
        450,
      );
      return /* 切换任务或继续输入时撤销旧校验。 */ () => {
        clearTimeout(timer);
        controller.abort();
      };
    },
    [plan, taskId, document, resume.items, running],
  );
  useEffect(
    /* 当前页检查通过后自动试填一次；旧试填结束再处理新模板，避免 Word 请求堆积。 */ () => {
      if (
        !active ||
        !autoPreview.current ||
        !plan ||
        !review?.ready ||
        review.missing === undefined ||
        busy ||
        loading ||
        running
      )
        return;
      autoPreview.current = false;
      void perform(trial);
    },
    [active, plan, review, busy, loading, running],
  );
  /** 带上当前人工修改和用户说明，交给 AI 自动补全并建立独立结果。 */
  async function repair(instructions = feedback) {
    const value = await api<TemplateAnalysis>(
      `/templates/analyses/${taskId}/repair`,
      "POST",
      { plan, document, items: resume.items, feedback: instructions },
    );
    if (isCurrent()) {
      openTask(value);
      // 只清除本次已提交的说明，修复问题时保留用户尚未提交的文字。
      if (instructions === feedback) setFeedback("");
    }
  }
  /** 检查短操作是否仍对应当前模板和当前简历的同一份资料。 */
  function isCurrent() {
    const current = latest.current;
    return (
      selectionVersion.current === selection &&
      current.taskId === taskId &&
      current.plan === plan &&
      current.document === document &&
      current.items === resume.items &&
      current.resumeId === resume.id
    );
  }
  /** 修改立即显示在画布，并撤销过期的校验和预览。 */
  function edit(value: TemplatePlan) {
    autoPreview.current = false;
    setPlan(value);
    setReview(null);
    setPreview(null);
    setView("structure");
  }
  /** 将读取和保存的失败原因显示在工作区，保持用户已编辑的映射。 */
  async function perform(work: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await work();
    } catch (error) {
      if (isCurrent()) setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 新文件识别失败单独显示文件名，保留当前模板结果并标明其归属。 */
  async function recognize() {
    setBusy(true);
    setNotice("");
    setImportError(null);
    autoPreview.current = false;
    try {
      const value = await api<TemplateAnalysis>("/templates/analyses", "POST", {
        path,
        document,
        items: resume.items,
      });
      if (isCurrent()) openTask(value);
    } catch (error) {
      if (isCurrent())
        setImportError({
          fileName: path.split(/[\\/]/).pop() || path,
          message: (error as Error).message,
        });
    } finally {
      setBusy(false);
    }
  }
  /** 内置版式直接展示；导入模板读取映射，快速切换时拒绝迟到结果。 */
  async function loadSaved(id: string) {
    libraryRequest.current?.abort();
    const controller = new AbortController();
    libraryRequest.current = controller;
    requestedId.current = id;
    setLibraryId(id);
    selectionVersion.current++;
    autoPreview.current = false;
    setLoading(!!id);
    setNotice("");
    setImportError(null);
    setAnalysis(null);
    setPlan(null);
    setReview(null);
    setPreview(null);
    setOpenedId("");
    setTaskId("");
    sessionStorage.removeItem("rm.template.analysis");
    sessionStorage.setItem("rm.template.library", id);
    if (!id) return;
    try {
      const value = await api<TemplateAnalysis>(
        `/templates/${id}/edit`,
        "POST",
        undefined,
        controller.signal,
      );
      if (!controller.signal.aborted) openTask(value, id);
    } catch (error) {
      if (!controller.signal.aborted) setNotice((error as Error).message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  /** 接入新分析或已保存模板快照，清除上一份模板的选区和试填。 */
  function openTask(value: TemplateAnalysis, templateId = "") {
    autoPreview.current = true;
    setImportError(null);
    setOpenedId(templateId);
    setLibraryId(templateId);
    setAnalysis(value);
    setPlan(null);
    setReview(null);
    setPreview(null);
    setSelected([]);
    setRangeAnchor(null);
    setView("summary");
    setFilter("all");
    setTaskId(value.id);
    sessionStorage.setItem("rm.template.analysis", value.id);
    if (templateId) sessionStorage.setItem("rm.template.library", templateId);
    else sessionStorage.removeItem("rm.template.library");
  }
  /** 点选文字、图片或同级范围，禁止跨单元格或跨部件拼接范围。 */
  function select(id: string, extend = false) {
    const node = nodes.find(
      /* 定位用户点击的节点。 */ (item) => item.id === id,
    );
    const anchor = rangeAnchor ?? (extend ? selected[0] : undefined);
    if (node?.kind === "image") {
      setSelected([id]);
      setRangeAnchor(null);
    } else if (anchor) {
      const ids = siblingRange(nodes, anchor, id);
      if (!ids.length) {
        setNotice("请选择同一层级的段落或表格行；不同单元格不能组成一个范围。");
        return;
      }
      setSelected(ids);
      setRangeAnchor(null);
      setNotice(`已选择 ${ids.length} 个同级区域。`);
    } else {
      setSelected([id]);
      setNotice("");
    }
    setView("structure");
  }
  /** 右侧定位始终选择单个位置，不继承尚未完成的范围选择。 */
  function locate(id: string) {
    setRangeAnchor(null);
    setSelected([id]);
    setView("structure");
  }
  /** 从固定操作区返回完整问题列表，并将键盘焦点和滚动位置移到原因。 */
  function showProblems() {
    setView("summary");
    requestAnimationFrame(
      /* 等待摘要挂载后定位，避免用户仍停留在长列表底部。 */ () =>
        workspace.current
          ?.querySelector<HTMLElement>(".template-questions")
          ?.focus(),
    );
  }
  /** 使用当前简历生成真实 Word 和分页图，不让迟到预览覆盖后续资料。 */
  async function trial() {
    const value = await api<Preview>(
      `/templates/analyses/${taskId}/preview`,
      "POST",
      { plan, document, items: resume.items },
    );
    if (isCurrent()) {
      setPreview(value);
      setView("preview");
    }
  }
  /** 保存为独立模板版本，再应用到仍在编辑的同一份简历。 */
  async function save() {
    const value = await api<{ id: string }>(
      `/templates/analyses/${taskId}/save`,
      "POST",
      { name, plan, document, items: resume.items },
    );
    await onChanged();
    if (isCurrent()) {
      requestedId.current = value.id;
      setOpenedId(value.id);
      setLibraryId(value.id);
      sessionStorage.setItem("rm.template.library", value.id);
      onSelected(value.id);
      setNotice(
        "模板已保存并用于当前简历。可返回个人信息或栏目编排继续填写资料。",
      );
    }
  }
  return (
    <section
      ref={workspace}
      className="template-adapter"
      aria-label="Word 模板工作区"
      style={
        {
          "--template-inspector-width": `${sizes.inspector}px`,
          "--template-preview-height": `${sizes.preview}px`,
        } as CSSProperties
      }
    >
      <div className="template-adaptive-workspace">
        <div className="template-source-bar" role="group" aria-label="模板操作">
          <div className="template-import-controls">
            <PathInput
              label="模板文件"
              kind="docx"
              placeholder="Word、PDF 或图片文件路径"
              value={path}
              disabled={busy || loading || running}
              onChange={
                /* 改选文件后撤销上一份文件的导入错误。 */ (value) => {
                  setPath(value);
                  setImportError(null);
                }
              }
            />
            <button
              className="primary"
              disabled={busy || loading || running || !path.trim()}
              onClick={
                /* 将所选文件交给 AI 识别，失败信息与当前模板分开呈现。 */ () =>
                  void recognize()
              }
            >
              <Sparkles size={16} />
              AI 识别
            </button>
          </div>
          <div className="template-library-controls">
            <label>
              模板库
              <select
                value={taskId && !savedId ? "imported" : savedId}
                disabled={running}
                onChange={
                  /* 查看所选版式，点击使用后才更新当前简历的模板引用。 */ (
                    event,
                  ) => {
                    void loadSaved(event.target.value);
                  }
                }
              >
                {taskId && !savedId && (
                  <option value="imported" disabled>
                    当前导入 · 尚未保存
                  </option>
                )}
                <TemplateOptions templates={templates} />
              </select>
            </label>
            {!builtin && (
              <button
                disabled={busy || loading || running || !saved}
                onClick={
                  /* 已加载时直接进入调整，保留人工修改；读取失败可在此重试。 */ () => {
                    if (openedId === savedId && plan) setView("structure");
                    else void loadSaved(savedId);
                  }
                }
              >
                {notice && !analysis ? "重新加载" : "调整映射"}
              </button>
            )}
            <button
              disabled={busy || loading || running || (!builtin && !saved)}
              onClick={
                /* 直接采用已保存的模板版本。 */ () => {
                  onSelected(builtin ? null : savedId);
                  setNotice("已用于当前简历。");
                }
              }
            >
              使用模板
            </button>
          </div>
        </div>
        {importError && (
          <div className="template-notice template-banner" role="alert">
            <strong>未能识别「{importError.fileName}」</strong>
            <div>{importError.message}</div>
            {analysis && (
              <div>
                下方仍显示「
                {analysis.file_name.replace(
                  /\.(docx?|docm|rtf|pdf|png|jpe?g)$/i,
                  "",
                )}
                」的已有结果。
              </div>
            )}
          </div>
        )}
        {analysis && (
          <TemplateProgress
            key={analysis.id}
            data={analysis}
            review={review}
            busy={busy}
            height={sizes.progress}
            maxHeight={sizes.progressMax}
            onResize={
              /* 记录动态区展开后的高度。 */ (value) =>
                onResize("templateProgress", value)
            }
            onReset={
              /* 恢复动态区的默认高度。 */ () =>
                onResize("templateProgress", DEFAULT_LAYOUT.templateProgress)
            }
            onCancel={
              /* 取消后立即呈现冻结的进度，服务端拒绝迟到结果。 */ () =>
                void perform(
                  /* 读取取消响应并保留本任务的活动记录。 */ async () => {
                    setAnalysis(
                      await api<TemplateAnalysis>(
                        `/templates/analyses/${taskId}/cancel`,
                        "POST",
                      ),
                    );
                  },
                )
            }
          />
        )}
        {notice && (
          <p className="template-notice template-banner" role="status">
            {notice}
          </p>
        )}
        {builtin ? (
          <BuiltinTemplate
            active={active}
            resume={{ ...resume, document }}
            revisions={revisions}
            previewSources={previewSources}
            run={
              /* 将预览下载错误显示在模板工作区。 */ (work) =>
                void perform(work)
            }
          />
        ) : !plan ? (
          !analysis && (
            <p className="template-workspace-empty" role="status">
              {loading ? (
                <LoaderCircle size={18} className="template-spinner" />
              ) : (
                <FileScan size={18} />
              )}
              {loading ? "正在加载模板…" : "暂无识别结果"}
            </p>
          )
        ) : (
          <>
            <fieldset
              disabled={busy || running}
              className="template-editor-layout"
            >
              <div className="template-visual-panel">
                <div className="template-canvas-toolbar">
                  <nav className="tabs" aria-label="模板视图">
                    <button
                      className={view === "summary" ? "active" : ""}
                      onClick={
                        /* 以资料和栏目概览代替底层段落清单。 */ () =>
                          setView("summary")
                      }
                    >
                      识别摘要
                    </button>
                    <button
                      className={view === "structure" ? "active" : ""}
                      onClick={
                        /* 切回可编辑的结构视图。 */ () => setView("structure")
                      }
                    >
                      精细调整
                    </button>
                    <button
                      className={view === "preview" ? "active" : ""}
                      disabled={!preview}
                      onClick={
                        /* 查看 Word 实际渲染的试填排版。 */ () =>
                          setView("preview")
                      }
                    >
                      Word 试填{preview?.pages ? ` · ${preview.pages} 页` : ""}
                    </button>
                  </nav>
                  <span
                    className="template-current-source"
                    title={analysis?.file_name}
                  >
                    {analysis?.file_name}
                  </span>
                  {view === "structure" && (
                    <label className="template-filter">
                      显示
                      <select
                        value={filter}
                        onChange={
                          /* 淡化已处理区域，突出待核对原文。 */ (event) =>
                            setFilter(
                              event.target.value as "all" | "unresolved",
                            )
                        }
                      >
                        <option value="all">全部内容</option>
                        <option value="unresolved">突出待处理</option>
                      </select>
                    </label>
                  )}
                </div>
                {view === "summary" ? (
                  <RecognitionSummary
                    nodes={nodes}
                    plan={plan}
                    review={review}
                    onLocate={locate}
                    onRepair={
                      /* 专门修复检查问题，不混入尚未提交的调整说明。 */ () =>
                        void perform(
                          /* 空说明仍会把当前方案及完整校验结果交给 AI。 */ () =>
                            repair(""),
                        )
                    }
                  />
                ) : view === "structure" ? (
                  <>
                    <div className="template-legend">
                      {Object.entries(REGION_LABELS)
                        .filter(
                          /* 空白位置只在画布内标注。 */ ([kind]) =>
                            kind !== "blank" && kind !== "container",
                        )
                        .map(
                          /* 使用文字和颜色共同说明每类用途。 */ ([
                            kind,
                            label,
                          ]) => (
                            <span
                              className={`template-status tone-${kind}`}
                              key={kind}
                            >
                              {label}
                            </span>
                          ),
                        )}
                    </div>
                    <p className="template-canvas-hint">
                      结构视图展示原文位置和映射；实际字体、分页与排版请查看
                      Word 试填。
                    </p>
                    {rangeAnchor && (
                      <div className="template-range-prompt">
                        已设置起点，请点击同级终点。
                        <button
                          onClick={
                            /* 退出范围选择，不修改当前方案。 */ () =>
                              setRangeAnchor(null)
                          }
                        >
                          取消选范围
                        </button>
                      </div>
                    )}
                    <TemplateCanvas
                      nodes={nodes}
                      plan={plan}
                      taskId={taskId}
                      selected={selected}
                      onSelect={select}
                      filter={filter}
                    />
                  </>
                ) : (
                  preview && (
                    <div className="template-preview-scroll">
                      <div className="template-preview">
                        <div className="actions">
                          <button
                            onClick={
                              /* 下载实际试填生成的 Word。 */ () =>
                                void perform(
                                  /* 执行当前操作并接收结果。 */ async () =>
                                    download(
                                      `/templates/analyses/${taskId}/previews/${preview.id}/resume.docx`,
                                      `${name}-试填.docx`,
                                    ),
                                )
                            }
                          >
                            下载试填 Word
                          </button>
                          {preview.pages && (
                            <button
                              onClick={
                                /* 下载 Word 渲染的 PDF。 */ () =>
                                  void perform(
                                    /* 执行当前操作并接收结果。 */ async () =>
                                      download(
                                        `/templates/analyses/${taskId}/previews/${preview.id}/resume.pdf`,
                                        `${name}-试填.pdf`,
                                      ),
                                  )
                              }
                            >
                              下载 PDF
                            </button>
                          )}
                        </div>
                        {preview.render_error && (
                          <p className="template-notice">
                            {preview.render_error}
                          </p>
                        )}
                        {Array.from(
                          { length: preview.pages ?? 0 },
                          /* 按实际页序展示全部页面。 */ (_, index) => (
                            <PrintedPage
                              key={`${preview.id}-${index}`}
                              path={`/templates/analyses/${taskId}/previews/${preview.id}/page-${index + 1}.svg`}
                              page={index + 1}
                            />
                          ),
                        )}
                      </div>
                    </div>
                  )
                )}
              </div>
              <ResizeHandle
                className="template-column-resize"
                label="调整模板映射区宽度"
                axis="x"
                reverse
                value={sizes.inspector}
                min={260}
                max={sizes.inspectorMax}
                onChange={
                  /* 调整右栏宽度，并让左侧预览自动占用剩余空间。 */ (value) =>
                    onResize("templateInspector", value)
                }
                onReset={
                  /* 恢复模板左右分栏的默认比例。 */ () =>
                    onResize(
                      "templateInspector",
                      DEFAULT_LAYOUT.templateInspector,
                    )
                }
              />
              <ResizeHandle
                className="template-stack-resize"
                label="调整模板预览区高度"
                axis="y"
                value={sizes.preview}
                min={240}
                max={1000}
                onChange={
                  /* 窄屏上下排列时独立调整预览高度。 */ (value) =>
                    onResize("templatePreview", value)
                }
                onReset={
                  /* 恢复窄屏预览的默认高度。 */ () =>
                    onResize("templatePreview", DEFAULT_LAYOUT.templatePreview)
                }
              />
              <aside className="template-inspector" aria-label="模板映射调整">
                <label>
                  模板名称
                  <input
                    value={name}
                    onChange={
                      /* 编辑另存时使用的名称。 */ (event) =>
                        setName(event.target.value)
                    }
                  />
                </label>
                {view === "structure" && (
                  <TemplateInspector
                    nodes={nodes}
                    plan={plan}
                    document={document}
                    selected={selected}
                    onChange={edit}
                    onSelect={locate}
                    onRange={
                      /* 将当前首节点设置为下次选择的起点。 */ () =>
                        setRangeAnchor(selected[0])
                    }
                  />
                )}
                <div className="template-ai-assistant">
                  <h3>
                    <Sparkles size={18} /> AI 助手
                  </h3>
                  <textarea
                    style={{ height: sizes.assistant }}
                    aria-label="告诉 AI 如何调整模板"
                    value={feedback}
                    maxLength={4000}
                    rows={4}
                    placeholder="说明要调整的内容，例如：顶部图片是证件照。"
                    onChange={
                      /* 保存用户对模板用途的文字说明。 */ (event) =>
                        setFeedback(event.target.value)
                    }
                  />
                  <ResizeHandle
                    className="template-assistant-resize"
                    label="调整 AI 输入区高度"
                    axis="y"
                    value={sizes.assistant}
                    min={64}
                    max={320}
                    onChange={
                      /* 保存 AI 输入区域的高度偏好。 */ (value) =>
                        onResize("templateAssistant", value)
                    }
                    onReset={
                      /* 恢复 AI 输入区默认高度。 */ () =>
                        onResize(
                          "templateAssistant",
                          DEFAULT_LAYOUT.templateAssistant,
                        )
                    }
                  />
                  <button
                    className="primary"
                    disabled={busy || running}
                    onClick={
                      /* 主动继续完善当前映射。 */ () => void perform(repair)
                    }
                  >
                    <Sparkles size={16} />
                    {feedback.trim() ? "按说明调整" : "AI 继续完善"}
                  </button>
                  {analysis?.repair_error && (
                    <p className="template-notice">
                      继续修正时遇到问题，已保留已有建议：
                      {analysis.repair_error}
                    </p>
                  )}
                </div>
                {analysis?.inventory.notices?.map(
                  /* 自动处理仅作说明，不阻止识别和试填。 */ (message) => (
                    <p className="subtle" key={message}>
                      {message}
                    </p>
                  ),
                )}
                {review?.notices?.map(
                  /* 在试填前说明复杂栏目的排版调整，方便核对模板效果。 */ (
                    message,
                  ) => (
                    <p className="subtle" key={message}>
                      {message}
                    </p>
                  ),
                )}
                <details className="template-analysis-summary">
                  <summary>
                    识别说明
                    {plan.warnings.length
                      ? ` · ${plan.warnings.length} 条提醒`
                      : ""}
                  </summary>
                  <p>{plan.summary}</p>
                  {plan.warnings.map(
                    /* 保留模型对不确定内容的具体说明。 */ (warning, index) => (
                      <p className="template-notice" key={index}>
                        {warning}
                      </p>
                    ),
                  )}
                </details>
                {view !== "summary" && review && (
                  <div className="template-review" aria-live="polite">
                    <p
                      className={
                        review.ready ? "template-ready" : "template-notice"
                      }
                    >
                      {review.ready
                        ? "当前模板检查通过，可查看试填并应用。"
                        : "还有需要确认的内容，可让 AI 继续完善。"}
                    </p>
                    {!review.ready && (
                      <button
                        onClick={
                          /* 返回集中问题列表，不重复显示大量段落。 */ () =>
                            setView("summary")
                        }
                      >
                        查看需要确认的内容
                      </button>
                    )}
                  </div>
                )}
                {view === "structure" && (
                  <AdvancedMapping
                    nodes={nodes}
                    plan={plan}
                    document={document}
                    taskId={taskId}
                    edit={edit}
                    onLocate={locate}
                  />
                )}
              </aside>
            </fieldset>
            <footer className="template-workspace-footer">
              <div className="template-footer-status">
                <span
                  id="template-action-status"
                  className={problems.length ? "template-notice" : "subtle"}
                  role="status"
                  title={trialDisabledReason || saveDisabledReason}
                >
                  {trialDisabledReason ||
                    saveDisabledReason ||
                    "试填已生成，可以保存并用于当前简历"}
                </span>
                {!!problems.length && (
                  <button disabled={busy || running} onClick={showProblems}>
                    查看问题 · {problems.length}
                  </button>
                )}
              </div>
              <div className="actions">
                <button
                  disabled={!!trialDisabledReason}
                  title={trialDisabledReason || undefined}
                  aria-describedby="template-action-status"
                  onClick={
                    /* 生成当前资料对应的 Word 试填。 */ () =>
                      void perform(trial)
                  }
                >
                  生成试填预览
                </button>
                <button
                  className="primary"
                  disabled={!!saveDisabledReason}
                  title={saveDisabledReason || undefined}
                  aria-describedby="template-action-status"
                  onClick={
                    /* 确认试填后保存独立版本并应用。 */ () =>
                      void perform(save)
                  }
                >
                  保存并用于当前简历
                </button>
              </div>
            </footer>
          </>
        )}
      </div>
    </section>
  );
}
