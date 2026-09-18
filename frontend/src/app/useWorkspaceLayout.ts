import { useEffect, useRef, useState } from "react";
import { useElementSize } from "../shared/hooks/useElementSize";
import { columnSizes, restoreLayout, type Layout } from "../shared/lib/layout";
import { loadLocal } from "../shared/lib/storage";

/** 集中管理布局偏好、可见区域边界、分隔条和放大预览退出行为。 */
export function useWorkspaceLayout() {
  const [sidebar, setSidebar] = useState(
    /* 仅在首次挂载时读取缓存或计算初始状态。 */ () =>
      !matchMedia("(max-width: 600px)").matches,
  );
  const [layout, setLayout] = useState(
    /* 仅在首次挂载时读取缓存或计算初始状态。 */ () =>
      restoreLayout(loadLocal<Partial<Layout> | null>("rm.layout", null)),
  );
  const [previewFocused, setPreviewFocused] = useState(false);
  const workbench = useRef<HTMLDivElement>(null);
  const workbenchSize = useElementSize(workbench);
  const columns = columnSizes(workbenchSize.width, sidebar, layout);
  // 内容随实际高度逐级精简，各个工作区都允许缩到单行步骤导航。
  const guideMin = 40;
  const guideMax = Math.max(guideMin, Math.min(280, innerHeight - 360));
  /** 更新单项布局偏好，尺寸边界由显示布局和分隔条统一约束。 */
  function resize(key: keyof Layout, value: number | boolean) {
    setLayout(
      /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
        previous,
      ) => ({ ...previous, [key]: value }),
    );
  }
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      localStorage.setItem("rm.layout", JSON.stringify(layout));
    },
    [layout],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (!previewFocused) return;
      /** 按 Esc 退出放大预览，恢复工作台的常规分栏。 */
      const leave = (event: KeyboardEvent) => {
        if (event.key === "Escape") setPreviewFocused(false);
      };
      document.addEventListener("keydown", leave);
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        document.removeEventListener("keydown", leave);
    },
    [previewFocused],
  );

  return {
    sidebar,
    setSidebar,
    layout,
    setLayout,
    previewFocused,
    setPreviewFocused,
    workbench,
    columns,
    guideMin,
    guideMax,
    resize,
  };
}
