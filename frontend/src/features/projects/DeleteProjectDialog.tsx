import { LoaderCircle, Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Project } from "../../shared/types/index";

/** 展示具体删除范围和占用原因；成功前保持模态层以免切换删除目标 */
export default function DeleteProjectDialog({
  project,
  childCount,
  blocker,
  onClose,
  onDelete,
}: {
  project: Project;
  childCount: number;
  blocker: string;
  onClose: () => void;
  onDelete: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const submitting = useRef(false);
  const titleId = useId();
  const descriptionId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const element = dialog.current!;
    const trigger = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (trigger instanceof HTMLElement && trigger.isConnected)
        trigger.focus();
      else document.getElementById("sidebar-collapse")?.focus();
    };
  }, []);
  /** 防止双击重复提交；失败留在原确认框并允许修正后重试 */
  async function remove() {
    if (submitting.current || blocker) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      await onDelete();
      onClose();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  return createPortal(
    <dialog
      ref={dialog}
      className="library-delete-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={(event) => {
        event.preventDefault();
        if (!submitting.current) onClose();
      }}
    >
      <h3 id={titleId}>{blocker ? "项目暂时无法删除" : "删除项目"}</h3>
      <p id={descriptionId}>
        {`确定删除“${project.name}”${childCount ? `及其 ${childCount} 个子项目` : ""}吗？项目经历、历史版本和 AI 会话将一并删除，此操作无法撤销。源码目录和已导出的文件会保留。`}
      </p>
      {(blocker || error) && (
        <p className="error" role="alert">
          {blocker || error}
        </p>
      )}
      <div className="actions">
        <button autoFocus disabled={busy} onClick={onClose}>
          取消
        </button>
        <button
          className="danger"
          disabled={busy || !!blocker}
          onClick={remove}
        >
          {busy ? (
            <LoaderCircle size={16} className="spin" />
          ) : (
            <Trash2 size={16} />
          )}
          {busy ? "正在删除…" : "删除项目"}
        </button>
      </div>
    </dialog>,
    document.body,
  );
}
