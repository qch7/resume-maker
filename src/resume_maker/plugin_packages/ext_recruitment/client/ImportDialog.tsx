import { useEffect, useRef, useState } from "react";
import { FileJson, Upload } from "lucide-react";
import { api } from "@resume-maker/plugin-sdk/shared/lib/api";
import Dialog from "./Dialog";
import type { ImportSummary, RecruitmentPreferences, Snapshot } from "./model";
import { readImportFile } from "./importFile";

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
  const [policy, setPolicy] = useState<
    RecruitmentPreferences["import_policy"] | null
  >(null);
  const [settingsError, setSettingsError] = useState("");
  const [settingsAttempt, setSettingsAttempt] = useState(0);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const working = useRef(false);
  const [preview, setPreview] = useState<ImportSummary | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setSettingsError("");
    void api<RecruitmentPreferences>(
      "/settings/recruitment",
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setPolicy(value.import_policy);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setSettingsError(failure.message);
      });
    return () => controller.abort();
  }, [settingsAttempt]);
  useEffect(() => {
    /** 拖放到窗口其他位置时也阻止浏览器直接打开文件 */
    function preventNavigation(event: DragEvent) {
      if (event.dataTransfer?.types.includes("Files")) event.preventDefault();
      if (event.type === "drop") {
        dragDepth.current = 0;
        setDragging(false);
      }
    }
    window.addEventListener("dragover", preventNavigation);
    window.addEventListener("drop", preventNavigation);
    return () => {
      window.removeEventListener("dragover", preventNavigation);
      window.removeEventListener("drop", preventNavigation);
    };
  }, []);
  useEffect(() => {
    if (!content || !policy) return;
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
    if (working.current) return;
    working.current = true;
    setBusy(true);
    try {
      await onRefresh();
      setAttempt((value) => value + 1);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  /** 文件选择和拖放走同一读取流程，处理期间拒绝新文件避免预览串位 */
  async function readFile(files: File[]) {
    if (!files.length || working.current || busy || checking || !policy) return;
    working.current = true;
    setContent("");
    setPreview(null);
    setError("");
    setName("");
    setBusy(true);
    try {
      const file = await readImportFile(files);
      if (file) {
        setName(file.name);
        setContent(file.content);
      }
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  /** 使用已经预览的版本和策略确认导入，失败时保留文件供重试 */
  async function confirm() {
    if (!preview || !policy || working.current) return;
    working.current = true;
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
      working.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog title="导入收藏夹" busy={busy} onClose={onClose}>
      <div className="recruitment-fields">
        <label
          className={`recruitment-upload ${dragging ? "dragging" : ""}`}
          aria-disabled={busy || checking || !policy}
          onDragEnter={(event) => {
            event.preventDefault();
            if (
              !busy &&
              !checking &&
              policy &&
              event.dataTransfer.types.includes("Files")
            ) {
              dragDepth.current += 1;
              setDragging(true);
            }
          }}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect =
              busy || checking || !policy ? "none" : "copy";
          }}
          onDragLeave={(event) => {
            event.preventDefault();
            dragDepth.current = Math.max(0, dragDepth.current - 1);
            if (!dragDepth.current) setDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            dragDepth.current = 0;
            setDragging(false);
            void readFile(Array.from(event.dataTransfer.files));
          }}
        >
          <FileJson size={30} />
          <strong>{dragging ? "松开以导入" : "拖入或选择 JSON 文件"}</strong>
          <span>最大 8 MB</span>
          <input
            type="file"
            accept=".json,application/json"
            aria-label="选择导入文件"
            disabled={busy || checking || !policy}
            onChange={(e) => {
              void readFile(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
        </label>
        {policy && (
          <p className="subtle">
            重复项：{policy === "keep" ? "保留本机" : "使用文件更新"}
          </p>
        )}
        {!policy && !settingsError && <p role="status">加载设置…</p>}
        {settingsError && (
          <p className="recruitment-error" role="alert">
            {settingsError}
            <button onClick={() => setSettingsAttempt((value) => value + 1)}>
              重新加载设置
            </button>
          </p>
        )}
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
