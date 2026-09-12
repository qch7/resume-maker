import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Download,
  FileDown,
  Plus,
  Save,
  X,
} from "lucide-react";
import { download, request } from "./api";
import type { Export, Resume, Revision, State } from "./types";

interface Props {
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
  const saved = state.resumes.find((r) => r.id === draft.id);
  const dirty =
    !saved ||
    JSON.stringify(saved.items) !== JSON.stringify(draft.items) ||
    saved.name !== draft.name ||
    saved.template_id !== draft.template_id;
  function move(index: number, delta: number) {
    const items = [...draft.items];
    [items[index], items[index + delta]] = [items[index + delta], items[index]];
    props.onChange({ ...draft, items });
  }
  return (
    <aside className="composition-pane">
      <header className="composition-header">
        <div className="section-heading">
          <h2>当前简历</h2>
          <span className="tag">{dirty ? "组合未保存" : "组合已保存"}</span>
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
          <button onClick={props.onSave} disabled={!draft.name.trim()}>
            <Save size={15} />
            保存组合
          </button>
          <button
            className="primary"
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
      </header>
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
      </nav>
      <div className="composition-scroll">
        {result && (
          <div className="export-result">
            <strong>
              {result.pages ? `已导出 · ${result.pages} 页` : "Word 已生成"}
            </strong>
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
            {draft.items.map((item, index) => {
              const revision = revisions[item.revision_id];
              if (!revision)
                return <p key={item.project_id}>正在读取经历版本…</p>;
              const value = revision.content;
              return (
                <article className="resume-project" key={item.project_id}>
                  <div className="resume-project-title">
                    <strong>{value.title}</strong>
                    <div className="row">
                      <button
                        className="icon-button"
                        aria-label={`上移项目 ${value.title}`}
                        disabled={index === 0}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp size={13} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label={`下移项目 ${value.title}`}
                        disabled={index === draft.items.length - 1}
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown size={13} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label={`移除项目 ${value.title}`}
                        onClick={() =>
                          props.onChange({
                            ...draft,
                            items: draft.items.filter((_, i) => i !== index),
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
                    .map((id) => value.highlights.find((h) => h.id === id))
                    .filter((h) => !!h)
                    .map((h) => (
                      <p key={h.id}>
                        <b>{h.title}：</b>
                        {h.text}
                      </p>
                    ))}
                  {!value.highlights.length && !value.description && (
                    <p className="subtle">尚未填写项目经历，可先分析源码。</p>
                  )}
                  <span className="version-note">
                    固定引用 r{revision.number}
                  </span>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}
