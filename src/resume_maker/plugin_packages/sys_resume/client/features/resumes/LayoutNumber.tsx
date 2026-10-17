import { Minus, Plus, RotateCcw } from "lucide-react";
import { useId, useEffect, useState } from "react";

export interface LayoutNumberOptions {
  min: number;
  max: number;
  step: number;
  fallback: number;
  halfPoints?: boolean;
}

/** 继承值首次点击采用基础值，其后按步长调整并限制范围 */
export function stepLayoutNumber(
  value: number | undefined,
  direction: number,
  options: LayoutNumberOptions,
): number {
  const next =
    value === undefined
      ? options.fallback
      : options.halfPoints
        ? direction > 0
          ? (Math.floor(value * 2) + 1) / 2
          : (Math.ceil(value * 2) - 1) / 2
        : value + direction * options.step;
  return Math.min(options.max, Math.max(options.min, Number(next.toFixed(6))));
}

/** 数值可直接输入、加减或恢复继承，无效输入不会写入草稿 */
export default function LayoutNumber({
  title,
  label = title,
  unit,
  value,
  options,
  onChange,
}: {
  title: string;
  label?: string;
  unit: string;
  value?: number;
  options: LayoutNumberOptions;
  onChange: (value: number | undefined) => void;
}) {
  const id = useId();
  const [text, setText] = useState(value === undefined ? "" : String(value));
  useEffect(() => {
    setText(value === undefined ? "" : String(value));
  }, [value]);
  return (
    <div className="layout-number-row">
      <label htmlFor={id}>{title}</label>
      <div className="layout-number-input">
        <button
          type="button"
          aria-label={`减小${label}`}
          title={
            value === undefined
              ? `采用基础值 ${options.fallback}${unit}`
              : undefined
          }
          disabled={value !== undefined && value <= options.min}
          onClick={() => onChange(stepLayoutNumber(value, -1, options))}
        >
          <Minus size={14} />
        </button>
        <input
          id={id}
          type="number"
          aria-label={label}
          min={options.min}
          max={options.max}
          step={options.step}
          placeholder="继承"
          value={text}
          onChange={(event) => {
            const raw = event.target.value;
            setText(raw);
            const number = raw ? Number(raw) : undefined;
            if (
              number === undefined ||
              (Number.isFinite(number) &&
                number >= options.min &&
                number <= options.max &&
                (!options.halfPoints || Number.isInteger(number * 2)))
            )
              onChange(number);
          }}
          onBlur={() => setText(value === undefined ? "" : String(value))}
        />
        <span aria-hidden="true">{unit}</span>
        <button
          type="button"
          aria-label={`增大${label}`}
          title={
            value === undefined
              ? `采用基础值 ${options.fallback}${unit}`
              : undefined
          }
          disabled={value !== undefined && value >= options.max}
          onClick={() => onChange(stepLayoutNumber(value, 1, options))}
        >
          <Plus size={14} />
        </button>
      </div>
      <button
        type="button"
        className="icon-button layout-number-reset"
        aria-label={`${label}恢复继承`}
        title="恢复继承"
        disabled={value === undefined}
        onClick={() => onChange(undefined)}
      >
        <RotateCcw size={14} />
      </button>
    </div>
  );
}
