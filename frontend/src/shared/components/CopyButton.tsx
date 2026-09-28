import { Check, Copy, CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";

/** 复制当前字段原文并在按钮旁显示成功或失败反馈 */
export default function CopyButton({
  label,
  text,
}: {
  label: string;
  text: string;
}) {
  const [status, setStatus] = useState<"idle" | "copying" | "copied" | "error">(
    "idle",
  );
  useEffect(() => {
    if (status !== "copied" && status !== "error") return;
    const timer = window.setTimeout(() => setStatus("idle"), 2500);
    return () => window.clearTimeout(timer);
  }, [status]);

  /** 剪贴板写入成功后才确认复制，失败时保留原字段供手动选择 */
  async function copy() {
    setStatus("copying");
    try {
      await navigator.clipboard.writeText(text);
      setStatus("copied");
    } catch {
      setStatus("error");
    }
  }

  const message =
    status === "copied"
      ? "已复制"
      : status === "error"
        ? "复制失败，请手动选择文字复制"
        : "";
  return (
    <span className="field-copy" data-status={status}>
      <button
        type="button"
        className="icon-button"
        aria-label={`复制${label}`}
        title={message || `复制${label}`}
        disabled={!text || status === "copying"}
        onClick={copy}
      >
        {status === "copied" ? (
          <Check size={15} aria-hidden="true" />
        ) : status === "error" ? (
          <CircleAlert size={15} aria-hidden="true" />
        ) : (
          <Copy size={15} aria-hidden="true" />
        )}
      </button>
      <span className="field-copy-feedback" role="status">
        {message}
      </span>
    </span>
  );
}
