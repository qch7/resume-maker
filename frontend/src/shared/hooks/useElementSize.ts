import { useLayoutEffect, useState, type RefObject } from "react";
/** 观察元素尺寸变化，可按需包含内边距和边框，卸载时解除观察。 */
export function useElementSize(
  ref: RefObject<HTMLElement | null>,
  box: "content-box" | "border-box" = "content-box",
) {
  const [size, setSize] = useState({ width: innerWidth, height: innerHeight });
  useLayoutEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (!ref.current) return;
      const observer = new ResizeObserver(
        /* 接收被观察元素的新尺寸，并同步布局状态。 */ ([entry]) => {
          const border = entry.borderBoxSize[0];
          const { width, height } =
            box === "border-box" && border
              ? { width: border.inlineSize, height: border.blockSize }
              : entry.contentRect;
          setSize({ width, height });
        },
      );
      observer.observe(ref.current, { box });
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        observer.disconnect();
    },
    [ref, box],
  );
  return size;
}
