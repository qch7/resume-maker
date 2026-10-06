import { useEffect, useState } from "react";
import { clientExtensions } from "./extensions";
import { runPluginCommand, shortcutCommand } from "./commands";

/** 命令菜单和快捷键共用执行入口，失败显示在本窗口 */
export default function CommandMenu({
  disabled,
  hidden = false,
  shortcuts = true,
}: {
  disabled: boolean;
  hidden?: boolean;
  shortcuts?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  /** 显示当前操作状态且保留失败后重试入口 */
  async function execute(id: string) {
    setError("");
    setBusy(id);
    try {
      await runPluginCommand(id);
      setOpen(false);
    } catch {
      setError("命令执行失败，请检查对应插件状态后重试。");
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    /** 快捷键仅在当前代次的工作区可编辑时接管事件 */
    function keydown(event: KeyboardEvent) {
      if (!shortcuts || disabled || busy) return;
      const id = shortcutCommand(event);
      if (!id) return;
      event.preventDefault();
      void execute(id);
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [disabled, busy, shortcuts]);
  return (
    <div className="plugin-commands">
      <button
        hidden={hidden}
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        插件命令
      </button>
      {!hidden && open && (
        <div aria-label="插件命令列表">
          {clientExtensions.list("commands").map((item) => (
            <button
              key={item.id}
              disabled={disabled || !!busy}
              onClick={() => void execute(item.id)}
            >
              {item.value.title}
              {item.value.shortcut && <kbd> {item.value.shortcut}</kbd>}
            </button>
          ))}
        </div>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
