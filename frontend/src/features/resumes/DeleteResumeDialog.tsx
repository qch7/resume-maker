import { Trash2, X } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import type { Resume } from "../../shared/types";

/** 删除前展示方案名称和影响范围 */
export default function DeleteResumeDialog({
  resume,
  onClose,
  onConfirm,
}: {
  resume: Resume;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(
    /* 打开原生模态窗口并在关闭后归还焦点 */ () => {
      const element = dialog.current;
      const trigger = document.activeElement;
      element?.showModal();
      return /* 清理模态状态并恢复键盘操作位置 */ () => {
        element?.close();
        if (trigger instanceof HTMLElement)
          trigger.focus({ preventScroll: true });
      };
    },
    [],
  );
  return createPortal(
    <dialog
      ref={dialog}
      className="delete-resume-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={onClose}
    >
      <div className="dialog-title">
        <h2 id={titleId}>删除简历方案</h2>
        <button
          className="icon-button"
          aria-label="关闭删除确认"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <div id={descriptionId}>
        <p>
          确定删除方案“<strong>{resume.name}</strong>”？
        </p>
        <p className="subtle">
          该方案及其未保存修改将从方案列表中移除。项目经历、Word
          模板和已导出的文件会保留。
        </p>
      </div>
      <div className="actions">
        <button onClick={onClose}>取消</button>
        <button className="danger-button" onClick={onConfirm}>
          <Trash2 size={15} />
          删除方案
        </button>
      </div>
    </dialog>,
    document.body,
  );
}
