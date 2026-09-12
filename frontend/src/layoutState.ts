export const DEFAULT_LAYOUT = {
  sidebar: 224,
  composer: 460,
  settings: 280,
  guide: 86,
  editor: 520,
  guideCollapsed: false,
};
export type Layout = typeof DEFAULT_LAYOUT;

export const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), Math.max(min, max));

export function restoreLayout(value: Partial<Layout> | null): Layout {
  const result = { ...DEFAULT_LAYOUT };
  for (const key of [
    "sidebar",
    "composer",
    "settings",
    "guide",
    "editor",
  ] as const) {
    const size = value?.[key];
    if (typeof size === "number" && Number.isFinite(size))
      result[key] = clamp(size, 40, 2000);
  }
  result.guideCollapsed = value?.guideCollapsed === true;
  return result;
}

export function columnSizes(width: number, visible: boolean, layout: Layout) {
  // Fit the current window without overwriting the user's preferred sizes.
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
