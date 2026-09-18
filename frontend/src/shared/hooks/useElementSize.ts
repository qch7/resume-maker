import { useLayoutEffect, useState, type RefObject } from "react";
/** 观察元素尺寸变化；可按需包含内边距和边框；卸载时解除观察 */
export function useElementSize(
  ref: RefObject<HTMLElement | null>,
  box: "content-box" | "border-box" = "content-box",
) {
  const [size, setSize] = useState({ width: innerWidth, height: innerHeight });
  useLayoutEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(
      /* 接收被观察元素的新尺寸并同步布局状态 */ ([entry]) => {
        const border = entry.borderBoxSize[0];
        const { width, height } =
          box === "border-box" && border
            ? { width: border.inlineSize, height: border.blockSize }
            : entry.contentRect;
        setSize({ width, height });
      },
    );
    observer.observe(ref.current, { box });
    return () => observer.disconnect();
  }, [ref, box]);
  return size;
}
