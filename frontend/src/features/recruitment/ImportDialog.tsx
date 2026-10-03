import { useEffect, useState } from "react";
import { FileJson, Upload } from "lucide-react";
import { api, download } from "../../shared/lib/api";
import Dialog from "./Dialog";
import type { ImportSummary, Snapshot } from "./model";

const ACTIONS = { added: "新增", updated: "更新", skipped: "跳过" };

/** 先检查文件和冲突策略，用户确认后才将有效条目合并到本机 */
export default function ImportDialog({
  snapshot,
  onImported,
  onRefresh,
  onClose,
}: {
  snapshot: Snapshot;
  onImported: (value: Snapshot, summary: ImportSummary) => void;
  onRefresh: () => Promise<void>;
  onClose: () => void;
}) {
  const [content, setContent] = useState("");
  const [name, setName] = useState("");
  const [policy, setPolicy] = useState<"keep" | "update">("keep");
  const [preview, setPreview] = useState<ImportSummary | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!content) return;
    const controller = new AbortController();
    setChecking(true);
    setPreview(null);
    setError("");
    void api<ImportSummary>(
      "/recruitment/import/preview",
      "POST",
      { revision: snapshot.revision, content, policy },
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setPreview(value);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => controller.abort();
  }, [content, policy, snapshot.revision, attempt]);
  /** 冲突或网络失败后刷新版本并重新预览当前文件 */
  async function retry() {
    setBusy(true);
    try {
      await onRefresh();
      setAttempt((value) => value + 1);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 读取用户选择的 UTF-8 文件，读取期间禁止再次选择以避免迟到结果覆盖 */
  async function readFile(file?: File) {
    setContent("");
    setPreview(null);
    setError("");
    setName(file?.name ?? "");
    if (!file) return;
    if (file.size > 8_000_000) {
      setError("文件超过 8 MB，请拆分后导入。");
      return;
    }
    setBusy(true);
    try {
      const text = await file.text();
      if (!text.trim()) throw new Error("文件为空，请选择收藏夹 JSON 文件。");
      setContent(text);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 使用已经预览的版本和策略确认导入，失败时保留文件供重试 */
  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ snapshot: Snapshot; summary: ImportSummary }>(
        "/recruitment/import",
        "POST",
        { revision: preview.revision, content, policy },
      );
      onImported(result.snapshot, result.summary);
      onClose();
    } catch (failure) {
      setError((failure as Error).message);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }
  /** 下载示例文件，失败时在当前窗口显示原因 */
  async function example() {
    try {
      await download(
        "/recruitment/examples/internet",
        "internet.bookmarks.json",
      );
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  return (
    <Dialog title="导入收藏夹" busy={busy} onClose={onClose}>
      <div className="recruitment-fields">
        <label className="recruitment-upload">
          <FileJson size={30} />
          <strong>选择收藏夹 JSON 文件</strong>
          <span>支持本页导出的文件及示例清单，最大 8 MB</span>
          <input
            type="file"
            accept=".json,application/json"
            aria-label="选择导入文件"
            disabled={busy || checking}
            onChange={(e) => {
              void readFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
        <div className="row">
          <button type="button" onClick={() => void example()}>
            下载互联网示例（30 家）
          </button>
        </div>
        <label>
          遇到相同 ID 的收藏
          <select
            value={policy}
            disabled={busy}
            onChange={(e) => {
              setPreview(null);
              setPolicy(e.target.value as "keep" | "update");
            }}
          >
            <option value="keep">保留本机内容，跳过重复项</option>
            <option value="update">使用文件内容更新重复项</option>
          </select>
        </label>
        <p className="subtle">更新会覆盖同 ID 条目的全部内容。</p>
        {name && <p className="recruitment-file-name">{name}</p>}
        {checking && <p role="status">正在检查文件…</p>}
        {preview && (
          <section className="recruitment-import-summary" aria-label="导入预览">
            <div className="recruitment-stats">
              <span>
                <b>{preview.added}</b>新增
              </span>
              <span>
                <b>{preview.updated}</b>更新
              </span>
              <span>
                <b>{preview.skipped}</b>跳过
              </span>
              <span>
                <b>{preview.domains_added}</b>新增领域
              </span>
              <span>
                <b>{preview.categories_added}</b>新增分类
              </span>
            </div>
            <ul>
              {preview.changes.map((item, index) => (
                <li key={index}>
                  <span>{item.name}</span>
                  <span className="tag">{ACTIONS[item.action]}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        {error && (
          <p className="recruitment-error" role="alert">
            {error}
            {content && (
              <button disabled={busy || checking} onClick={() => void retry()}>
                刷新并重新检查
              </button>
            )}
          </p>
        )}
      </div>
      <footer>
        <button disabled={busy} onClick={onClose}>
          取消
        </button>
        <button
          className="primary"
          disabled={!preview || busy || checking}
          onClick={() => void confirm()}
        >
          <Upload size={15} />
          {busy ? "正在导入…" : "确认导入"}
        </button>
      </footer>
    </Dialog>
  );
}
