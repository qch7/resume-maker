import { Undo2, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../shared/lib/api";
import { flushDrafts } from "../../shared/lib/draftRegistry";
import type { ProjectDetail } from "../../shared/types";

/** 撤销前二次确认；锁定完整草稿集合；取消或并发冲突时保留原有输入 */
export default function DiscardChangesDialog({
  projectId,
  revisionId,
  number,
  onClose,
  onConfirm,
}: {
  projectId: string;
  revisionId: string;
  number: number;
  onClose: () => void;
  onConfirm: (versions: Record<string, number>) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [versions, setVersions] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  useEffect(
    /* 模态期间禁止继续编辑；先写完防抖草稿再读取确认基线 */ () => {
      const element = dialog.current!;
      const trigger = document.activeElement;
      let active = true;
      element.showModal();
      void (
        /* 确认只针对本次读取的版本；其他窗口后续修改会触发冲突 */ (async () => {
          try {
            await flushDrafts();
            const detail = await api<ProjectDetail>(
              `/projects/${projectId}?revision_id=${revisionId}`,
            );
            if (active)
              setVersions(
                Object.fromEntries(
                  detail.working.drafts.map(
                    /* 记录全部字段草稿的版本；新增或删除也必须参与校验 */ (
                      draft,
                    ) => [draft.field, draft.version],
                  ),
                ),
              );
          } catch (failure) {
            if (active) setError((failure as Error).message);
          }
        })()
      );
      return /* 关闭时不改写草稿；归还操作焦点 */ () => {
        active = false;
        element.close();
        if (trigger instanceof HTMLElement && trigger.isConnected)
          trigger.focus({ preventScroll: true });
      };
    },
    [projectId, revisionId],
  );
  /** 仅在用户二次确认后执行撤销；失败仍保留窗口和全部改动 */
  async function confirm() {
    if (!versions || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      await onConfirm(versions);
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
      className="delete-resume-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={
        /* 请求执行期间不能误关确认窗口 */ (event) => {
          event.preventDefault();
          if (!busy) onClose();
        }
      }
    >
      <div className="dialog-title">
        <h2 id={titleId}>撤销未提交改动</h2>
        <button
          className="icon-button"
          aria-label="关闭撤销确认"
          disabled={busy}
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <div id={descriptionId}>
        <p>确定撤销当前项目在 r{number} 上的全部未提交改动？</p>
        <p className="subtle">
          基本信息、条目增删和排序、亮点内容将恢复到 r{number}
          。当前简历的隐藏、显示设置会保留。
        </p>
      </div>
      {error && (
        <p className="warning" role="alert">
          {error}
        </p>
      )}
      {!versions && !error && (
        <p className="subtle" role="status">
          正在读取待撤销改动…
        </p>
      )}
      <div className="actions">
        <button autoFocus disabled={busy} onClick={onClose}>
          取消
        </button>
        <button
          className="danger-button"
          disabled={busy || !versions || !!error}
          onClick={confirm}
        >
          <Undo2 size={15} />
          {busy ? "正在撤销…" : "确认撤销"}
        </button>
      </div>
    </dialog>,
    document.body,
  );
}
