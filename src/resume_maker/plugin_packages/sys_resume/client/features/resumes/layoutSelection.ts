import { createContext } from "react";

export interface LayoutSelection {
  key: string;
  request: number;
  select: (key: string) => void;
}

/** 内容预览及设置面板共享文字选择，只在当前编辑器内生效 */
export const LayoutSelectionContext = createContext<LayoutSelection | null>(
  null,
);
