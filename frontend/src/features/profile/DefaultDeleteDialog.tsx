import { useEffect, useRef } from "react";

/** 已填写的默认项删除前再次确认，取消时不改变设置副本。 */
export default function DefaultDeleteDialog({
  label,
  onConfirm,
  onClose,
}: {
  label: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(
    /* 第二层弹窗独立管理焦点，关闭后返回设置界面。 */ () => {
      const element = dialog.current!;
      element.showModal();
      return /* 卸载时释放模态焦点。 */ () => element.close();
    },
    [],
  );
  return (
    <dialog
      ref={dialog}
      className="defaults-delete-dialog"
      aria-labelledby="default-delete-title"
      onCancel={
        /* Escape 只取消本次删除。 */ (event) => {
          event.preventDefault();
          onClose();
        }
      }
    >
      <h2 id="default-delete-title">确认删除默认项？</h2>
      <p>
        “{label}
        ”已有填写内容。删除后，此项将从当前表单和新简历的默认设置中移除。
      </p>
      <p className="subtle">
        当前简历的已有内容会保留并隐藏，其他已保存简历不受影响。点击“保存设置”后生效。
      </p>
      <div className="actions">
        <button autoFocus onClick={onClose}>
          取消
        </button>
        <button className="danger" onClick={onConfirm}>
          确认删除
        </button>
      </div>
    </dialog>
  );
}
