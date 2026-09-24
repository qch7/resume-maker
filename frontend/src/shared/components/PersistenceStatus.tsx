import { useEffect, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { storage, storageVersion, subscribeStorage } from "../lib/storage";

/** 展示自动保存失败和窗口冲突，处理前始终保留本页输入 */
export default function PersistenceStatus() {
  useSyncExternalStore(subscribeStorage, storageVersion);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [host, setHost] = useState<Element>(document.body);
  useEffect(() => {
    /** 模态窗口打开时把恢复操作放进顶层窗口，避免按钮被背景禁用 */
    function locate() {
      setHost(
        [...document.querySelectorAll("dialog[open]")].at(-1) ?? document.body,
      );
    }
    const observer = new MutationObserver(locate);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["open"],
    });
    locate();
    return () => observer.disconnect();
  }, []);
  const issue = storage.issues()[0];
  const copies = storage.recoveries();
  const pending = storage.pending();
  const [showSaved, setShowSaved] = useState(false);
  useEffect(() => {
    if (pending) {
      setShowSaved(true);
      return;
    }
    const timer = setTimeout(() => setShowSaved(false), 2000);
    return () => clearTimeout(timer);
  }, [pending]);
  /** 处理保存及冲突，载入远端前确保其他输入已经落盘 */
  async function perform(work: () => Promise<void>, reload = false) {
    setBusy(true);
    setError("");
    try {
      await work();
      if (reload) {
        await storage.prepareReload();
        location.reload();
      }
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!pending && !issue && !error && !copies.length && !showSaved) return null;
  return createPortal(
    <aside
      className={`persistence-status ${issue || error ? "warning" : ""}`}
      aria-live="polite"
    >
      {(pending || issue || error || showSaved) && (
        <span>
          {error ||
            issue?.error ||
            (pending ? "正在保存草稿…" : "草稿已保存到本机")}
        </span>
      )}
      {pending && storage.warning() && <span>{storage.warning()}</span>}
      {issue?.conflict ? (
        <>
          <button
            disabled={busy}
            onClick={() =>
              void perform(() => storage.resolve(issue.key, "local"))
            }
          >
            保留本页修改
          </button>
          <button
            disabled={busy}
            onClick={() =>
              void perform(() => storage.resolve(issue.key, "remote"), true)
            }
          >
            载入已保存内容
          </button>
        </>
      ) : (
        issue && (
          <button disabled={busy} onClick={() => void perform(storage.flush)}>
            重试保存
          </button>
        )
      )}
      {!!copies.length && (
        <details>
          <summary>查看恢复副本（{copies.length}）</summary>
          <p>这些内容来自其他未同步窗口或冲突处理，保留供复制核对。</p>
          {copies.map((copy, index) => (
            <textarea
              key={copy.id}
              readOnly
              aria-label={`恢复副本 ${index + 1}`}
              value={copy.value ?? ""}
            />
          ))}
        </details>
      )}
    </aside>,
    host,
  );
}
