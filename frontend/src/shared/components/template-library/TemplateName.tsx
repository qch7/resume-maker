import { Check, Pencil, X } from "lucide-react";
import { useRef, useState } from "react";

/** 在详情标题内重命名；提交失败保留输入；取消不写入数据库 */
export default function TemplateName({
  name,
  editable,
  pending,
  onSave,
}: {
  name: string;
  editable: boolean;
  pending: boolean;
  onSave: (name: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const editButton = useRef<HTMLButtonElement>(null);

  /** 结束编辑并恢复键盘焦点以免下一次 Escape 意外作用于旧输入框 */
  function finish() {
    setEditing(false);
    requestAnimationFrame(
      /* 输入框卸载后将焦点还给名称旁的编辑按钮 */ () =>
        editButton.current?.focus(),
    );
  }

  return editing ? (
    <form
      className="library-name-editor"
      onSubmit={
        /* 仅成功写入后关闭编辑；空白名称保持禁用 */ async (event) => {
          event.preventDefault();
          if (pending || !draft.trim()) return;
          if (draft.trim() === name || (await onSave(draft.trim()))) finish();
        }
      }
      onKeyDown={
        /* Escape 只取消名称编辑且不关闭整个模板库 */ (event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            if (!pending) finish();
          }
        }
      }
    >
      <input
        autoFocus
        aria-label="模板名称"
        maxLength={200}
        value={draft}
        disabled={pending}
        onFocus={
          /* 全选原名称；方便直接替换 */ (event) => event.target.select()
        }
        onChange={
          /* 输入仅保留在当前标题草稿中 */ (event) =>
            setDraft(event.target.value)
        }
      />
      <button
        className="icon-button"
        type="submit"
        aria-label="保存模板名称"
        title="保存名称"
        disabled={pending || !draft.trim()}
      >
        <Check size={16} />
      </button>
      <button
        className="icon-button"
        type="button"
        aria-label="取消修改名称"
        title="取消"
        disabled={pending}
        onClick={finish}
      >
        <X size={16} />
      </button>
    </form>
  ) : (
    <div className="library-detail-name">
      <h3>{name}</h3>
      {editable && (
        <button
          ref={editButton}
          className="icon-button"
          aria-label="编辑模板名称"
          title="编辑名称"
          disabled={pending}
          onClick={
            /* 每次开始编辑读取当前已保存名称且不沿用取消的草稿 */ () => {
              setDraft(name);
              setEditing(true);
            }
          }
        >
          <Pencil size={14} />
        </button>
      )}
    </div>
  );
}
