import { useLayoutEffect, useState, type RefObject } from "react";
/** 观察元素尺寸变化，可按需包含内边距、边框，卸载时解除观察 */
export function useElementSize(
  ref: RefObject<HTMLElement | null>,
  box: "content-box" | "border-box" = "content-box",
) {
  const [size, setSize] = useState({ width: innerWidth, height: innerHeight });
  useLayoutEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => {
      const border = entry.borderBoxSize[0];
      const { width, height } =
        box === "border-box" && border
          ? { width: border.inlineSize, height: border.blockSize }
          : entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(ref.current, { box });
    return () => observer.disconnect();
  }, [ref, box]);
  return size;
}
