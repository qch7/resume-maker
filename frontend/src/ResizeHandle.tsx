import { useLayoutEffect, useRef, useState, type RefObject } from "react";
import { clamp } from "./layoutState";

export function useElementSize(ref: RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: innerWidth, height: innerHeight });
  useLayoutEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

export default function ResizeHandle({
  label,
  axis,
  value,
  min,
  max,
  reverse = false,
  className = "",
  onChange,
  onReset,
}: {
  label: string;
  axis: "x" | "y";
  value: number;
  min: number;
  max: number;
  reverse?: boolean;
  className?: string;
  onChange: (value: number) => void;
  onReset: () => void;
}) {
  const drag = useRef<{ coordinate: number; value: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const direction = reverse ? -1 : 1;
  return (
    <div
      className={`resize-handle resize-${axis} ${className} ${dragging ? "dragging" : ""}`}
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={Math.round(max)}
      aria-valuetext={`${Math.round(value)} 像素`}
      title={`${label}：拖动调整，方向键微调，双击复位`}
      onDoubleClick={onReset}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = {
          coordinate: axis === "x" ? event.clientX : event.clientY,
          value,
        };
        setDragging(true);
      }}
      onPointerMove={(event) => {
        if (!drag.current) return;
        const coordinate = axis === "x" ? event.clientX : event.clientY;
        onChange(
          clamp(
            drag.current.value +
              (coordinate - drag.current.coordinate) * direction,
            min,
            max,
          ),
        );
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId))
          event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onLostPointerCapture={() => {
        drag.current = null;
        setDragging(false);
      }}
      onKeyDown={(event) => {
        const increase = axis === "x" ? "ArrowRight" : "ArrowDown";
        const decrease = axis === "x" ? "ArrowLeft" : "ArrowUp";
        if (![increase, decrease, "Home", "End", "Enter"].includes(event.key))
          return;
        event.preventDefault();
        if (event.key === "Enter") return onReset();
        const next =
          event.key === "Home"
            ? min
            : event.key === "End"
              ? max
              : value +
                (event.key === increase ? 1 : -1) *
                  direction *
                  (event.shiftKey ? 40 : 10);
        onChange(clamp(next, min, max));
      }}
    >
      <span />
    </div>
  );
}
