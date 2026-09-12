import { useLayoutEffect, useState, type RefObject } from "react";
/** 观察元素尺寸变化，组件卸载时解除观察，供布局计算使用。 */
export function useElementSize(ref: RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: innerWidth, height: innerHeight });
  useLayoutEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (!ref.current) return;
      const observer = new ResizeObserver(
        /* 接收被观察元素的新尺寸，并同步布局状态。 */ ([entry]) => {
          const { width, height } = entry.contentRect;
          setSize({ width, height });
        },
      );
      observer.observe(ref.current);
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        observer.disconnect();
    },
    [ref],
  );
  return size;
}
