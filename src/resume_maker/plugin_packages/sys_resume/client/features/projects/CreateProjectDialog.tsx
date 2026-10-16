import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { LoaderCircle, Plus } from "lucide-react";
import type { Project } from "@resume-maker/plugin-sdk/shared/types/index";

/** 创建手工项目，失败保留名称，成功后交由工作台定位编辑区 */
export default function CreateProjectDialog({
  onClose,
  onCreate,
  onCreated,
}: {
  onClose: () => void;
  onCreate: (name: string) => Promise<Project>;
  onCreated: (project: Project) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const submitting = useRef(false);
  const titleId = useId();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const element = dialog.current!;
    const trigger = document.activeElement;
    element.showModal();
    return () => {
      element.close();
      if (trigger instanceof HTMLElement && trigger.isConnected)
        trigger.focus({ preventScroll: true });
    };
  }, []);
  /** 同步锁住提交，避免双击或连续按回车创建重复项目 */
  async function create(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || !name.trim()) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const project = await onCreate(name.trim());
      onCreated(project);
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
      onCancel={(event) => {
        event.preventDefault();
        if (!submitting.current) onClose();
      }}
    >
      <form onSubmit={(event) => void create(event)}>
        <h3 id={titleId}>新建手工项目</h3>
        <p className="subtle">创建后直接填写项目描述，源码目录可稍后关联。</p>
        <label>
          项目名称
          <input
            autoFocus
            required
            maxLength={200}
            value={name}
            disabled={busy}
            placeholder="例如：课程设计、实习项目"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="primary" disabled={busy || !name.trim()}>
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Plus size={16} />
            )}
            {busy ? "正在创建…" : "创建并编辑"}
          </button>
        </div>
      </form>
    </dialog>,
    document.body,
  );
}
