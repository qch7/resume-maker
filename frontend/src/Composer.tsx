import { useEffect, useRef, useState, type CSSProperties } from "react";
import { arrayMove } from "@dnd-kit/sortable";
import {
  ArrowDown,
  ArrowUp,
  Download,
  FileDown,
  Maximize2,
  Minimize2,
  Plus,
  Save,
  X,
} from "lucide-react";
import { download, request } from "./api";
import { isCurrentExport, sameComposition } from "./workflowState";
import ResizeHandle, { useElementSize } from "./ResizeHandle";
import { clamp, DEFAULT_LAYOUT } from "./layoutState";
import { SortableItem, SortableList } from "./SortableList";
import type { Export, Resume, Revision, State } from "./types";

interface Props {
  settingsHeight: number;
  onSettingsHeight: (value: number) => void;
  previewFocused: boolean;
  onFocusPreview: () => void;
  state: State;
  draft: Resume;
  revisions: Record<string, Revision>;
  result: Export | null;
  exporting: boolean;
  onChange: (value: Resume) => void;
  onChoose: (id: string) => void;
  onSave: () => void;
  onExport: () => void;
  onNew: () => void;
  onTemplates: () => void;
  onEditProject: (id: string) => void;
  run: (work: () => Promise<void>) => void;
}

function PrintedPage({ exportId, page }: { exportId: string; page: number }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let objectUrl = "",
      stopped = false;
    void request(`/exports/${exportId}/page-${page}.png`)
      .then((r) => r.blob())
      .then((blob) => {
        if (!stopped) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        }
      })
      .catch((e) => {
        if (!stopped) setError(e.message);
      });
    return () => {
      stopped = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [exportId, page]);
  return url ? (
    <img
      className="printed-page"
      src={url}
      alt={`Word 实际渲染第 ${page} 页`}
    />
  ) : (
    <p className="subtle">{error || `载入第 ${page} 页…`}</p>
  );
}

export default function Composer(props: Props) {
  const { draft, state, revisions, result } = props;
  const [tab, setTab] = useState<"content" | "print">("content");
  const pane = useRef<HTMLElement>(null);
  const size = useElementSize(pane);
  const settingsMax = Math.max(80, size.height - 188);
  const settingsHeight = clamp(props.settingsHeight, 80, settingsMax);
  const saved = state.resumes.find((r) => r.id === draft.id);
  const dirty = !sameComposition(saved, draft);
  const currentExport = isCurrentExport(result, draft);
  function move(from: number, to: number) {
    props.onChange({ ...draft, items: arrayMove(draft.items, from, to) });
  }
  return (
    <aside
      className="composition-pane"
      ref={pane}
      style={{ "--settings-height": `${settingsHeight}px` } as CSSProperties}
    >
      <header className="composition-header">
        <div className="section-heading">
          <h2>当前简历</h2>
          <span className={`tag ${dirty ? "warning-tag" : ""}`}>
            {dirty ? "组合未保存" : "组合已保存"}
          </span>
        </div>
        <div className="resume-picker">
          <select
            aria-label="简历方案"
            value={draft.id}
            onChange={(e) => props.onChoose(e.target.value)}
          >
            {!draft.id && <option value="">未命名方案</option>}
            {state.resumes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <button
            className="icon-button"
            aria-label="新建简历方案"
            onClick={props.onNew}
          >
            <Plus size={17} />
          </button>
        </div>
        <label>
          方案名称
          <input
            value={draft.name}
            onChange={(e) => props.onChange({ ...draft, name: e.target.value })}
          />
        </label>
        <div className="template-picker">
          <label>
            Word 模板
            <select
              data-guide="template-select"
              value={draft.template_id ?? ""}
              onChange={(e) =>
                props.onChange({
                  ...draft,
                  template_id: e.target.value || null,
                })
              }
            >
              <option value="">选择模板</option>
              {state.templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <button className="text-button" onClick={props.onTemplates}>
            管理模板
          </button>
        </div>
        <div className="actions">
          {saved && saved.version !== draft.version && (
            <button onClick={() => props.onChange(saved)}>
              载入服务器组合
            </button>
          )}
          <button
            data-guide="composition-save"
            onClick={props.onSave}
            disabled={!draft.name.trim()}
          >
            <Save size={15} />
            保存组合
          </button>
          <button
            className="primary"
            data-guide="export"
            onClick={props.onExport}
            disabled={
              props.exporting ||
              !draft.template_id ||
              !draft.items.length ||
              !draft.name.trim()
            }
          >
            <FileDown size={15} />
            {props.exporting ? "正在生成并渲染…" : "导出 Word"}
          </button>
        </div>
        <p className="composition-summary">
          已选 {draft.items.length} 个项目 ·{" "}
          {draft.items.reduce(
            (sum, item) => sum + item.highlight_ids.length,
            0,
          )}{" "}
          条亮点
        </p>
        {props.exporting && (
          <div className="export-progress" role="status">
            <span />
            正在生成文档并检查分页…
          </div>
        )}
      </header>
      <ResizeHandle
        className="settings-resize"
        label="调整设置与预览高度"
        axis="y"
        value={settingsHeight}
        min={80}
        max={settingsMax}
        onChange={props.onSettingsHeight}
        onReset={() => props.onSettingsHeight(DEFAULT_LAYOUT.settings)}
      />
      <section className="preview-pane" aria-label="简历预览">
        <nav className="tabs preview-tabs">
          <button
            className={tab === "content" ? "active" : ""}
            onClick={() => setTab("content")}
          >
            内容预览
          </button>
          <button
            className={tab === "print" ? "active" : ""}
            disabled={!result}
            onClick={() => setTab("print")}
          >
            上次导出预览{result?.pages ? ` · ${result.pages} 页` : ""}
          </button>
          <button
            className="icon-button preview-focus"
            aria-label={props.previewFocused ? "退出放大预览" : "放大预览"}
            title={props.previewFocused ? "退出放大预览（Esc）" : "放大预览"}
            aria-pressed={props.previewFocused}
            onClick={props.onFocusPreview}
          >
            {props.previewFocused ? (
              <Minimize2 size={16} />
            ) : (
              <Maximize2 size={16} />
            )}
          </button>
        </nav>
        <div className="composition-scroll">
          {result && (
            <div className="export-result">
              <strong>
                {currentExport ? "当前组合已导出" : "上次导出"}
                {result.pages ? ` · ${result.pages} 页` : " · Word 已生成"}
              </strong>
              {!currentExport && (
                <span className="warning">
                  组合已变化，重新导出后更新文件与预览。
                </span>
              )}
              <span className="subtle">
                {new Date(result.created_at).toLocaleString()}
              </span>
              {result.render_error && (
                <p className="warning">{result.render_error}</p>
              )}
              <div className="actions">
                <button
                  onClick={() =>
                    props.run(() =>
                      download(
                        `/exports/${result.id}/resume.docx`,
                        `${draft.name}.docx`,
                      ),
                    )
                  }
                >
                  <Download size={14} />
                  Word
                </button>
                {result.pages && (
                  <button
                    onClick={() =>
                      props.run(() =>
                        download(
                          `/exports/${result.id}/resume.pdf`,
                          `${draft.name}.pdf`,
                        ),
                      )
                    }
                  >
                    PDF
                  </button>
                )}
                <button
                  className="text-button"
                  onClick={() =>
                    props.run(() =>
                      download(
                        `/exports/${result.id}/manifest.json`,
                        "export-manifest.json",
                      ),
                    )
                  }
                >
                  版本清单
                </button>
              </div>
            </div>
          )}
          {tab === "print" && result ? (
            <div className="print-preview">
              {Array.from({ length: result.pages ?? 0 }, (_, i) => (
                <PrintedPage
                  key={`${result.id}.${i}`}
                  exportId={result.id}
                  page={i + 1}
                />
              ))}
            </div>
          ) : (
            <div className="resume-paper">
              <div className="paper-heading">项目经历</div>
              {!draft.items.length && (
                <div className="empty compact">
                  <p>从左侧勾选项目</p>
                  <span>选择经历版本与亮点，再调整项目顺序。</span>
                </div>
              )}
              <SortableList
                key={draft.id}
                items={draft.items.map((item) => ({
                  id: item.project_id,
                  label: revisions[item.revision_id]?.content.title || "项目",
                }))}
                disabled={draft.items.some(
                  (item) => !revisions[item.revision_id],
                )}
                onMove={move}
              >
                {draft.items.map((item, index) => {
                  const revision = revisions[item.revision_id];
                  if (!revision)
                    return <p key={item.project_id}>正在读取经历版本…</p>;
                  const value = revision.content;
                  return (
                    <SortableItem
                      as="article"
                      className="resume-project"
                      key={item.project_id}
                      id={item.project_id}
                      label={`项目 ${value.title}`}
                    >
                      {(handle) => (
                        <>
                          <div className="resume-project-title">
                            <strong>{value.title}</strong>
                            <div className="row">
                              <button
                                className="icon-button"
                                aria-label={`上移项目 ${value.title}`}
                                disabled={index === 0}
                                onClick={() => move(index, index - 1)}
                              >
                                <ArrowUp size={13} />
                              </button>
                              {handle}
                              <button
                                className="icon-button"
                                aria-label={`下移项目 ${value.title}`}
                                disabled={index === draft.items.length - 1}
                                onClick={() => move(index, index + 1)}
                              >
                                <ArrowDown size={13} />
                              </button>
                              <button
                                className="icon-button"
                                aria-label={`移除项目 ${value.title}`}
                                onClick={() =>
                                  props.onChange({
                                    ...draft,
                                    items: draft.items.filter(
                                      (_, i) => i !== index,
                                    ),
                                  })
                                }
                              >
                                <X size={13} />
                              </button>
                            </div>
                          </div>
                          <span className="resume-period">
                            {value.period} {value.role}
                          </span>
                          {value.stack.length > 0 && (
                            <p>
                              <b>技术栈：</b>
                              {value.stack.join("、")}
                            </p>
                          )}
                          {value.description && (
                            <p>
                              <b>项目描述：</b>
                              {value.description}
                            </p>
                          )}
                          {item.highlight_ids
                            .map((id) =>
                              value.highlights.find((h) => h.id === id),
                            )
                            .filter((h) => !!h)
                            .map((h) => (
                              <p key={h.id}>
                                <b>{h.title}：</b>
                                {h.text}
                              </p>
                            ))}
                          {!value.highlights.length && !value.description && (
                            <p className="subtle">
                              尚未填写项目经历，可先分析源码。
                            </p>
                          )}
                          <span className="version-note">
                            固定引用 r{revision.number}
                          </span>
                          {state.projects.find(
                            (project) => project.id === item.project_id,
                          )?.head_revision !== revision.id && (
                            <button
                              className="text-button revision-update"
                              onClick={() =>
                                props.onEditProject(item.project_id)
                              }
                            >
                              有更新的经历版本 · 查看
                            </button>
                          )}
                        </>
                      )}
                    </SortableItem>
                  );
                })}
              </SortableList>
            </div>
          )}
        </div>
      </section>
    </aside>
  );
}
