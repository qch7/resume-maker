import { useEffect, useRef, useState } from "react";
import { FileCheck2, FileScan, LoaderCircle, Sparkles, X } from "lucide-react";
import PathInput from "../../shared/components/PathInput";
import { api, download } from "../../shared/lib/api";
import type { Resume, Template } from "../../shared/types";
import { newDocument } from "../profile/document";
import PrintedPage from "../resumes/PrintedPage";
import AdvancedMapping from "./AdvancedMapping";
import ManualTemplate from "./ManualTemplate";
import TemplateCanvas from "./TemplateCanvas";
import TemplateInspector from "./TemplateInspector";
import { nodeLabel } from "./mapping";
import { REGION_LABELS, siblingRange } from "./visual";
import type { MappingReview, TemplateAnalysis, TemplatePlan } from "./types";

type Preview = {
  id: string;
  pages: number | null;
  render_error: string | null;
};

/** 在独立工作区识别、可视化调整、试填和保存完整 Word 模板。 */
export default function TemplateAdapter({
  resume,
  templates,
  onChanged,
  onSelected,
}: {
  resume: Resume;
  templates: Template[];
  onChanged: () => Promise<void>;
  onSelected: (id: string) => void;
}) {
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [libraryId, setLibraryId] = useState("");
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
  const [view, setView] = useState<"structure" | "preview">("structure");
  const [filter, setFilter] = useState<"all" | "unresolved">("all");
  const [mode, setMode] = useState<"adaptive" | "manual">("adaptive");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const document = resume.document ?? newDocument();
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
  const nodes = analysis?.inventory.nodes ?? [];
  const savedId = libraryId || resume.template_id || "";
  const saved = templates.find(
    /* 定位模板库中当前选项。 */ (item) => item.id === savedId,
  );
  useEffect(
    /* 资料变化后旧试填不再代表当前简历，必须重新生成。 */ () => {
      setPreview(null);
      setView("structure");
    },
    [resume.document, resume.items, resume.id],
  );
  useEffect(
    /* 只轮询当前任务；离开功能区保持挂载，继续接收分析进度。 */ () => {
      if (!taskId) return;
      const controller = new AbortController();
      let timer: ReturnType<typeof setTimeout>;
      /** 响应后才安排下一轮，结束后不再覆盖用户的人工调整。 */
      async function poll() {
        try {
          const value = await api<TemplateAnalysis>(
            `/templates/analyses/${taskId}`,
            "GET",
            undefined,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          setAnalysis(value);
          if (value.status === "running") timer = setTimeout(poll, 1200);
          else {
            setPlan(value.plan);
            setReview(value.review);
            setName(value.file_name.replace(/\.docx$/i, ""));
            setSelected(
              value.plan?.fields[0] ? [value.plan.fields[0].node] : [],
            );
            if (value.error) setNotice(value.error);
          }
        } catch (error) {
          if (!controller.signal.aborted) {
            setNotice((error as Error).message);
            sessionStorage.removeItem("rm.template.analysis");
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
  /** 检查短操作是否仍对应当前模板和当前简历的同一份资料。 */
  function isCurrent() {
    const current = latest.current;
    return (
      current.taskId === taskId &&
      current.plan === plan &&
      current.document === document &&
      current.items === resume.items &&
      current.resumeId === resume.id
    );
  }
  /** 修改立即显示在画布，并撤销过期的校验和预览。 */
  function edit(value: TemplatePlan) {
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
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 接入新分析或已保存模板快照，清除上一份模板的选区和试填。 */
  function openTask(value: TemplateAnalysis) {
    setAnalysis(value);
    setPlan(null);
    setReview(null);
    setPreview(null);
    setSelected([]);
    setRangeAnchor(null);
    setView("structure");
    setFilter("all");
    setTaskId(value.id);
    sessionStorage.setItem("rm.template.analysis", value.id);
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
  /** 检查全部映射并返回仍需人工处理的具体原文。 */
  async function check() {
    const value = await api<MappingReview>(
      `/templates/analyses/${taskId}/review`,
      "POST",
      { plan },
    );
    if (isCurrent()) setReview(value);
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
    setLibraryId(value.id);
    if (isCurrent()) {
      onSelected(value.id);
      setNotice(
        "模板已保存并用于当前简历。可返回个人信息或栏目编排继续填写资料。",
      );
    } else
      setNotice("模板已保存到模板库。当前简历已切换，可在模板库中选择使用。");
  }
  return (
    <section className="template-adapter" aria-label="Word 模板工作区">
      <header className="template-workspace-header">
        <div>
          <h2>
            <FileScan size={23} />
            Word 模板
          </h2>
          <p className="subtle">
            识别整份简历，点击原文核对映射，再用当前资料试填。
          </p>
        </div>
        <nav className="tabs" aria-label="模板模式">
          <button
            className={mode === "adaptive" ? "active" : ""}
            onClick={
              /* 返回完整模板编辑，保留手动工具状态。 */ () =>
                setMode("adaptive")
            }
          >
            完整简历适配
          </button>
          <button
            className={mode === "manual" ? "active" : ""}
            onClick={/* 打开仅替换项目区的独立工具。 */ () => setMode("manual")}
          >
            手动项目区
          </button>
        </nav>
      </header>
      <div className="template-manual-workspace" hidden={mode !== "manual"}>
        <ManualTemplate onChanged={onChanged} />
      </div>
      <div className="template-adaptive-workspace" hidden={mode !== "adaptive"}>
        <div className="template-source-bar">
          <PathInput
            label="导入 Word 文档"
            kind="docx"
            placeholder="D:\...\陌生简历.docx"
            value={path}
            disabled={busy || running}
            onChange={setPath}
          />
          <button
            className="primary"
            disabled={busy || running || !path.trim()}
            onClick={
              /* 将模板文本交给设置中的 AI 识别，个人字段值不传给模型。 */ () =>
                void perform(
                  /* 执行当前操作并接收结果。 */ async () => {
                    openTask(
                      await api<TemplateAnalysis>(
                        "/templates/analyses",
                        "POST",
                        { path, document },
                      ),
                    );
                  },
                )
            }
          >
            <Sparkles size={16} />
            AI 识别
          </button>
          <div className="template-source-divider" />
          <label>
            已保存模板
            <select
              value={saved?.id ?? ""}
              disabled={busy || running}
              onChange={
                /* 选择要继续调整或使用的模板。 */ (event) =>
                  setLibraryId(event.target.value)
              }
            >
              <option value="" disabled>
                选择模板
              </option>
              {templates.map(
                /* 区分整份简历与仅项目区模板。 */ (item) => (
                  <option value={item.id} key={item.id}>
                    {item.name}
                    {item.kind === "projects" ? " · 项目区" : ""}
                  </option>
                ),
              )}
            </select>
          </label>
          <button
            disabled={busy || running || saved?.kind !== "adaptive"}
            onClick={
              /* 从已保存原文与映射建立可编辑副本，不再次调用 AI。 */ () =>
                void perform(
                  /* 执行当前操作并接收结果。 */ async () => {
                    openTask(
                      await api<TemplateAnalysis>(
                        `/templates/${savedId}/edit`,
                        "POST",
                      ),
                    );
                  },
                )
            }
          >
            调整映射
          </button>
          <button
            disabled={busy || running || !saved}
            onClick={
              /* 直接采用已保存的模板版本。 */ () => {
                onSelected(savedId);
                setNotice("已用于当前简历。");
              }
            }
          >
            使用模板
          </button>
        </div>
        {running && (
          <div className="template-progress" role="status">
            <LoaderCircle size={17} className="template-spinner" />
            <span>{analysis.activity}</span>
            <button
              disabled={busy}
              onClick={
                /* 主动取消分析，保留原文快照。 */ () =>
                  void perform(
                    /* 执行当前操作并接收结果。 */ async () => {
                      setAnalysis(
                        await api<TemplateAnalysis>(
                          `/templates/analyses/${taskId}/cancel`,
                          "POST",
                        ),
                      );
                    },
                  )
              }
            >
              <X size={15} />
              取消分析
            </button>
          </div>
        )}
        {notice && (
          <p className="template-notice template-banner" role="status">
            {notice}
          </p>
        )}
        {!plan ? (
          <div className="template-workspace-empty">
            <FileScan size={48} />
            <h3>
              {running ? "正在识别模板结构" : "让你的 Word 简历成为可复用模板"}
            </h3>
            <p>导入 .docx 后，AI 会识别姓名、联系方式、照片和各个经历栏目。</p>
            <div className="template-empty-steps">
              <span>1 · 导入并识别</span>
              <span>2 · 点击原文调整</span>
              <span>3 · 试填并应用</span>
            </div>
            <p className="subtle">
              模板文字会交给设置中的 AI 分析。原文件保留；识别结果可逐项修正。
            </p>
          </div>
        ) : (
          <>
            <fieldset disabled={busy} className="template-editor-layout">
              <div className="template-visual-panel">
                <div className="template-canvas-toolbar">
                  <nav className="tabs" aria-label="模板视图">
                    <button
                      className={view === "structure" ? "active" : ""}
                      onClick={
                        /* 切回可编辑的结构视图。 */ () => setView("structure")
                      }
                    >
                      识别结构
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
                {view === "structure" ? (
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
                              path={`/templates/analyses/${taskId}/previews/${preview.id}/page-${index + 1}.png`}
                              page={index + 1}
                            />
                          ),
                        )}
                      </div>
                    </div>
                  )
                )}
              </div>
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
                {review && (
                  <div className="template-review" aria-live="polite">
                    {review.errors.map(
                      /* 逐项显示需要纠正的结构错误。 */ (error, index) => (
                        <p className="template-notice" key={index}>
                          {error}
                        </p>
                      ),
                    )}
                    {review.unresolved.length > 0 && (
                      <details open>
                        <summary>
                          待处理原文与图片 · {review.unresolved.length}
                        </summary>
                        {review.unresolved.map(
                          /* 点击待处理条目定位到画布并开启右侧调整。 */ (
                            node,
                          ) => (
                            <button
                              className="template-unresolved-link"
                              key={node.id}
                              onClick={
                                /* 定位并保留当前映射。 */ () => locate(node.id)
                              }
                            >
                              {nodeLabel(node)}
                            </button>
                          ),
                        )}
                      </details>
                    )}
                    {review.ready && (
                      <p className="template-ready">
                        <FileCheck2 size={17} />
                        映射完整，请试填核对内容和排版。
                      </p>
                    )}
                  </div>
                )}
                <AdvancedMapping
                  nodes={nodes}
                  plan={plan}
                  document={document}
                  taskId={taskId}
                  edit={edit}
                  onLocate={locate}
                />
              </aside>
            </fieldset>
            <footer className="template-workspace-footer">
              <span className="subtle">
                {busy
                  ? "正在处理…"
                  : !review
                    ? "映射已修改，请重新检查"
                    : review.ready
                      ? "全部原文已分类"
                      : `还有 ${review.errors.length} 项问题、${review.unresolved.length} 处待处理`}
              </span>
              <div className="actions">
                <button
                  disabled={busy}
                  onClick={
                    /* 校验刚调整的完整方案。 */ () => void perform(check)
                  }
                >
                  检查映射
                </button>
                <button
                  disabled={busy || !review?.ready}
                  onClick={
                    /* 生成当前资料对应的 Word 试填。 */ () =>
                      void perform(trial)
                  }
                >
                  生成试填预览
                </button>
                <button
                  className="primary"
                  disabled={busy || !review?.ready || !preview || !name.trim()}
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
