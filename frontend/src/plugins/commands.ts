import { clientExtensions, normalizeShortcut } from "./extensions";
import { windowNotice } from "./window";

/** 所有命令入口遵守窗口冻结，执行前重新查找当前贡献 */
export async function runPluginCommand(id: string) {
  if (windowNotice())
    throw new Error("插件正在切换，请等待草稿保存和能力协商完成。");
  await clientExtensions.execute(id);
}

/** 输入框、组合输入和长按不会触发插件命令 */
export function shortcutCommand(event: KeyboardEvent): string | undefined {
  const target = event.target;
  if (
    event.defaultPrevented ||
    event.repeat ||
    event.isComposing ||
    !(event.ctrlKey || event.metaKey) ||
    (event.ctrlKey && event.metaKey) ||
    (target instanceof Element &&
      target.closest(
        "input,textarea,select,[contenteditable]:not([contenteditable='false'])",
      )) ||
    !/^[a-z0-9]$/i.test(event.key)
  )
    return;
  const shortcut = normalizeShortcut(
    [
      "mod",
      ...(event.shiftKey ? ["shift"] : []),
      ...(event.altKey ? ["alt"] : []),
      event.key.toLowerCase(),
    ].join("+"),
  );
  return clientExtensions
    .list("commands")
    .find(
      (item) =>
        item.value.shortcut &&
        normalizeShortcut(item.value.shortcut) === shortcut,
    )?.id;
}
