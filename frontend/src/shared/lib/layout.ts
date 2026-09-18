export const DEFAULT_LAYOUT = {
  sidebar: 224,
  composer: 460,
  settings: 280,
  guide: 144,
  editor: 520,
  chatInput: 180,
  guideCollapsed: false,
  templateInspector: 320,
  templateProgress: 150,
  templatePreview: 520,
  templateAssistant: 100,
};
export type Layout = typeof DEFAULT_LAYOUT;

/** 把数值限制在有效边界内；即使最大值偏小也保留最小可用尺寸 */
export const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), Math.max(min, max));

/** 忽略损坏或非数值的布局缓存；为有效偏好补齐默认尺寸 */
export function restoreLayout(value: Partial<Layout> | null): Layout {
  const result = { ...DEFAULT_LAYOUT };
  for (const key of [
    "sidebar",
    "composer",
    "settings",
    "guide",
    "editor",
    "chatInput",
    "templateInspector",
    "templateProgress",
    "templatePreview",
    "templateAssistant",
  ] as const) {
    const size = value?.[key];
    if (typeof size === "number" && Number.isFinite(size))
      result[key] = clamp(size, 40, 2000);
  }
  result.guideCollapsed = value?.guideCollapsed === true;
  return result;
}

/** 按当前视口计算可用列宽；保留用户偏好且确保编辑区可见 */
export function columnSizes(width: number, visible: boolean, layout: Layout) {
  // 按当前窗口约束显示尺寸；窗口缩小不覆盖用户保存的布局偏好
  const wide = width > 980;
  const sidebar =
    visible && width > 600
      ? clamp(layout.sidebar, 160, Math.min(520, width - (wide ? 636 : 328)))
      : 0;
  const composer = clamp(
    layout.composer,
    300,
    width - sidebar - (sidebar ? 16 : 8) - 320,
  );
  return {
    sidebar,
    composer,
    sidebarMax: Math.max(
      160,
      Math.min(520, width - (wide ? composer + 336 : 328)),
    ),
    composerMax: Math.max(300, width - sidebar - (sidebar ? 16 : 8) - 320),
  };
}

/** 限制模板模块的显示尺寸；缩窗时保留预览空间且不改写已保存的尺寸偏好 */
export function templateSizes(width: number, height: number, layout: Layout) {
  const inspectorMax = Math.max(260, width - 368);
  const progressMax = Math.max(72, Math.min(420, height - 360));
  return {
    inspector: clamp(layout.templateInspector, 260, inspectorMax),
    inspectorMax,
    progress: clamp(layout.templateProgress, 72, progressMax),
    progressMax,
    preview: clamp(layout.templatePreview, 240, 1000),
    assistant: clamp(layout.templateAssistant, 64, 320),
  };
}
