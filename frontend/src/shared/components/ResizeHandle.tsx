import { useRef, useState } from "react";
import { clamp } from "../lib/layout";

/** 提供指针和键盘可访问的分隔条，限制尺寸范围并支持复位。 */
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
      onPointerDown={
        /* 记录拖动起点并捕获指针，确保移出手柄后仍能继续拖动。 */ (event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.currentTarget.focus();
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = {
            coordinate: axis === "x" ? event.clientX : event.clientY,
            value,
          };
          setDragging(true);
        }
      }
      onPointerMove={
        /* 按指针位移更新尺寸，并限制在当前可用边界内。 */ (event) => {
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
        }
      }
      onPointerUp={
        /* 释放本次指针捕获，由捕获结束事件清理拖动状态。 */ (event) => {
          if (event.currentTarget.hasPointerCapture(event.pointerId))
            event.currentTarget.releasePointerCapture(event.pointerId);
        }
      }
      onLostPointerCapture={
        /* 清空拖动起点并恢复分隔条的空闲状态。 */ () => {
          drag.current = null;
          setDragging(false);
        }
      }
      onKeyDown={
        /* 处理方向键与边界快捷键，提供无鼠标的尺寸调整。 */ (event) => {
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
        }
      }
    >
      <span />
    </div>
  );
}
