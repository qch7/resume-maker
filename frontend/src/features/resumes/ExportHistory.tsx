import { Download, FileText, History, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useRemote } from "../../shared/hooks/useRemote";
import { download } from "../../shared/lib/api";
import type { Export, Resume } from "../../shared/types";
import { isCurrentExport } from "./composition";
import PrintedPage from "./PrintedPage";

/** 展示某次导出的固定快照，下载名采用当时名称以免与后续改名混淆。 */
function ExportCard({
  result,
  draft,
  previewChanged,
}: {
  result: Export;
  draft: Resume;
  previewChanged: boolean;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const current = !previewChanged && isCurrentExport(result, draft);
  const name = result.manifest?.resume.name || "简历";
  /** 直接下载历史文件，不依赖编辑区的草稿提交是否成功。 */
  async function saveFile(file: string, filename: string) {
    setPending(true);
    setError("");
    try {
      await download(`/exports/${result.id}/${file}`, filename);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setPending(false);
    }
  }
  return (
    <article
      className="resume-export-card"
      aria-label={`${name}，${new Date(result.created_at).toLocaleString()} 导出`}
    >
      <div className="resume-export-thumbnail">
        {result.pages ? (
          <PrintedPage exportId={result.id} page={1} />
        ) : (
          <div>
            <FileText size={34} />
            <span>Word 文档</span>
          </div>
        )}
      </div>
      <div className="resume-export-details">
        <div className="section-heading">
          <strong title={name}>{name}</strong>
          <span className={`tag ${current ? "success-tag" : ""}`}>
            {current ? "与当前内容一致" : "历史成品"}
          </span>
        </div>
        <span className="subtle">
          {new Date(result.created_at).toLocaleString()} ·{" "}
          {result.pages ? `${result.pages} 页` : "Word 已生成"}
        </span>
        {result.render_error && (
          <p className="warning">{result.render_error}</p>
        )}
        <div className="actions">
          <button
            disabled={pending}
            onClick={
              /* 下载这次导出的 Word 文件。 */ () =>
                void saveFile("resume.docx", `${name}.docx`)
            }
          >
            <Download size={14} />
            Word
          </button>
          {result.pages && (
            <button
              disabled={pending}
              onClick={
                /* PDF 与 Word 来自同一次导出。 */ () =>
                  void saveFile("resume.pdf", `${name}.pdf`)
              }
            >
              PDF
            </button>
          )}
          <button
            className="text-button"
            disabled={pending}
            onClick={
              /* 保存固定版本的追溯清单。 */ () =>
                void saveFile("manifest.json", `${name}-版本清单.json`)
            }
          >
            版本清单
          </button>
        </div>
        {error && (
          <p className="warning" role="alert">
            {error}
          </p>
        )}
      </div>
    </article>
  );
}

/** 每次打开或完成导出后读取全部历史，并即时合并刚生成的文件。 */
export default function ExportHistory({
  draft,
  result,
  previewChanged,
}: {
  draft: Resume;
  result: Export | null;
  previewChanged: boolean;
}) {
  const [attempt, setAttempt] = useState(0);
  const latest = result?.resume_id === draft.id ? result : null;
  const history = useRemote<Export[]>(
    draft.id ? `/resumes/${draft.id}/exports` : null,
    (latest ? Date.parse(latest.created_at) : 0) + attempt,
  );
  const rows = [...(latest ? [latest] : []), ...(history.data ?? [])]
    .filter(
      /* 合并异步历史响应时，同一导出只展示一次。 */ (item, index, all) =>
        all.findIndex(
          /* 使用导出标识去重，不根据时间误合并。 */ (other) =>
            other.id === item.id,
        ) === index,
    )
    .sort(
      /* 最新成品优先显示。 */ (a, b) =>
        b.created_at.localeCompare(a.created_at),
    );
  return (
    <section className="resume-export-history" aria-label="导出记录">
      <div className="section-heading">
        <div className="row">
          <History size={17} />
          <h3>导出记录</h3>
          <span className="count-badge">{rows.length}</span>
        </div>
        <button
          className="text-button"
          disabled={!draft.id}
          onClick={
            /* 重新获取文件列表，失败后也可重试。 */ () =>
              setAttempt(attempt + 1)
          }
        >
          <RefreshCw size={13} />
          刷新
        </button>
      </div>
      {history.error && (
        <p className="warning" role="alert">
          导出记录读取失败：{history.error}
        </p>
      )}
      {!!draft.id && !history.ready && !history.error && !rows.length ? (
        <p className="subtle" role="status">
          正在读取导出记录…
        </p>
      ) : !rows.length && !history.error ? (
        <div className="resume-library-empty">
          <FileText size={36} strokeWidth={1.2} />
          <h3>第一份成品，从这里开始</h3>
          <p>
            选择喜欢的模板，点击“导出 Word”。
            <br />
            生成的 Word、PDF 和版本清单会保存在这里。
          </p>
        </div>
      ) : null}
      <div className="resume-export-grid">
        {rows.map(
          /* 每份成品绑定其不可变导出标识。 */ (item) => (
            <ExportCard
              key={item.id}
              result={item}
              draft={draft}
              previewChanged={previewChanged}
            />
          ),
        )}
      </div>
    </section>
  );
}
