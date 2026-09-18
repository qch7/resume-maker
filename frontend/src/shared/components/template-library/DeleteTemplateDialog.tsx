import { Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../lib/api";
import type { LibraryState, LibraryTemplate } from "./library";

/** 确认具体模板后再移除，失败时保留确认框与原列表，避免误报成功。 */
export default function DeleteTemplateDialog({
  template,
  permanent,
  onClose,
  onDeleted,
}: {
  template: LibraryTemplate;
  permanent: boolean;
  onClose: () => void;
  onDeleted: (state: LibraryState) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const alive = useRef(true);
  const submitting = useRef(false);
  const titleId = useId();
  const descriptionId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(
    /* 嵌套原生模态层阻止背后选择变化，关闭后恢复触发按钮的键盘焦点。 */ () => {
      alive.current = true;
      const element = dialog.current!;
      const trigger = document.activeElement;
      element.showModal();
      return /* 请求结束前父组件卸载也不能发布迟到结果。 */ () => {
        alive.current = false;
        element.close();
        if (trigger instanceof HTMLElement && trigger.isConnected)
          trigger.focus();
      };
    },
    [],
  );
  /** 固定删除目标并阻止重复提交，只在服务确认后刷新模板与数量。 */
  async function remove() {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const state = await api<LibraryState>(
        `/template-library/items/${encodeURIComponent(template.id)}${permanent ? "?permanent=true" : ""}`,
        "DELETE",
      );
      if (alive.current) onDeleted(state);
    } catch (failure) {
      if (alive.current) setError((failure as Error).message);
    } finally {
      submitting.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return createPortal(
    <dialog
      ref={dialog}
      className="library-delete-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={
        /* Escape 只关闭本层确认，提交期间等待服务返回。 */ (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (!submitting.current) onClose();
        }
      }
    >
      <h3 id={titleId}>{permanent ? "永久删除模板" : "移入回收站"}</h3>
      <p id={descriptionId}>
        {permanent
          ? `确定永久删除“${template.name}”吗？模板文件、保存的识别结果和专属缓存将被清理，此操作无法撤销。`
          : `确定将“${template.name}”移入项目回收站吗？30 天内可以恢复，之后将自动永久删除。被简历引用的模板不能删除。`}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button autoFocus disabled={busy} onClick={onClose}>
          取消
        </button>
        <button className="danger" disabled={busy} onClick={remove}>
          <Trash2 size={16} />
          {busy ? "正在处理…" : permanent ? "永久删除" : "移入回收站"}
        </button>
      </div>
    </dialog>,
    document.body,
  );
}
