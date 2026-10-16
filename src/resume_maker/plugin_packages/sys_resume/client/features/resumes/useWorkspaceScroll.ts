import { useLayoutEffect } from "react";
import { readWorkspaceSession, saveWorkspaceSession } from "./workspaceSession";

const PANELS = [
  ".workspace-scroll",
  ".messages",
  ".sidebar-body",
  ".composition-scroll",
];

/** 等待对应正文挂载后恢复位置，卸载前保留各面板最后一次滚动 */
export function useWorkspaceScroll(key: string, ready: boolean) {
  useLayoutEffect(() => {
    if (!ready) return;
    const storageKey = `scroll.${key}`;
    const saved = readWorkspaceSession<Record<string, number>>(storageKey, {});
    const positions: Record<string, number> = {};
    const panels = PANELS.flatMap((selector) => {
      const panel = document.querySelector<HTMLElement>(selector);
      return panel ? [{ selector, panel }] : [];
    });
    for (const { selector, panel } of panels) {
      const top = saved?.[selector];
      panel.scrollTop =
        typeof top === "number" && Number.isFinite(top) ? Math.max(0, top) : 0;
      positions[selector] = panel.scrollTop;
    }
    /** 滚动只记位置，不触发正文刷新或草稿提交 */
    function save(event: Event) {
      const item = panels.find(({ panel }) => panel === event.target);
      if (!item) return;
      positions[item.selector] = item.panel.scrollTop;
      saveWorkspaceSession(storageKey, positions);
    }
    document.addEventListener("scroll", save, true);
    return () => {
      document.removeEventListener("scroll", save, true);
      saveWorkspaceSession(storageKey, positions);
    };
  }, [key, ready]);
}
