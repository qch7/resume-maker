import { ChevronDown, ChevronUp } from "lucide-react";

/** 在一个图标宽度内竖排上下移动按钮，分别保留键盘焦点和边界禁用 */
export default function MoveButtons({
  label,
  upDisabled,
  downDisabled,
  onUp,
  onDown,
}: {
  label: string;
  upDisabled: boolean;
  downDisabled: boolean;
  onUp: () => void;
  onDown: () => void;
}) {
  return (
    <div className="move-buttons" role="group" aria-label={`调整${label}顺序`}>
      <button
        type="button"
        className="icon-button"
        aria-label={`上移${label}`}
        title={`上移${label}`}
        disabled={upDisabled}
        onClick={onUp}
      >
        <ChevronUp size={13} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="icon-button"
        aria-label={`下移${label}`}
        title={`下移${label}`}
        disabled={downDisabled}
        onClick={onDown}
      >
        <ChevronDown size={13} aria-hidden="true" />
      </button>
    </div>
  );
}
