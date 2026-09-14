import { Eye, EyeOff } from "lucide-react";
import type { ReactNode } from "react";

/** 以睁眼和闭眼展示显隐状态，编辑时可切换，正文始终保留。 */
export function VisibilityButton({
  label,
  hidden = false,
  disabled = false,
  onToggle,
}: {
  label: string;
  hidden?: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  const action = `${hidden ? "显示" : "隐藏"}${label}`;
  return (
    <button
      type="button"
      className="icon-button visibility-toggle"
      aria-label={action}
      title={action}
      aria-pressed={hidden}
      disabled={disabled}
      onClick={onToggle}
    >
      {hidden ? <EyeOff size={15} /> : <Eye size={15} />}
    </button>
  );
}

/** 将标签、输入与显隐按钮分开，点击眼睛不会触发输入框的标签行为。 */
export default function VisibilityField({
  id,
  label,
  hidden,
  disabled,
  onToggle,
  children,
}: {
  id: string;
  label: string;
  hidden?: boolean;
  disabled?: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="visibility-field" data-hidden={hidden || undefined}>
      <label htmlFor={id}>{label}</label>
      <div className="field-control">
        {children}
        <VisibilityButton
          label={label}
          hidden={hidden}
          disabled={disabled}
          onToggle={onToggle}
        />
      </div>
    </div>
  );
}
