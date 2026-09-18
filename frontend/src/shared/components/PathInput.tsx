import { useEffect, useId, useRef, useState } from "react";
import { FileSearch, FolderOpen, LoaderCircle } from "lucide-react";
import { api } from "../lib/api";
import { appendPath } from "../lib/paths";

interface Props {
  label: string;
  value: string;
  onChange: (value: string) => void;
  kind: "docx" | "folder" | "executable";
  placeholder?: string;
  disabled?: boolean;
  multiline?: boolean;
}

/** 统一路径填写与 Windows 原生选择；取消、卸载或表单切换不会覆盖原值 */
export default function PathInput({
  label,
  value,
  onChange,
  kind,
  placeholder,
  disabled = false,
  multiline = false,
}: Props) {
  const id = useId();
  const [selecting, setSelecting] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  const latest = useRef({ value, onChange, disabled });
  latest.current = { value, onChange, disabled };
  useEffect(
    /* 关闭表单后忽略尚未返回的选择以免修改别的项目或简历 */ () => {
      return /* 中止前端订阅；原生窗口仍可通过自身取消按钮关闭 */ () =>
        pending.current?.abort();
    },
    [],
  );
  /** 请求系统选择窗口且只有当前输入仍对应原值时才回填 */
  async function browse() {
    if (pending.current || disabled) return;
    const controller = new AbortController();
    pending.current = controller;
    setSelecting(true);
    setError("");
    try {
      const initial = value.split("\n").filter(Boolean).at(-1) ?? "";
      const result = await api<{ path: string | null }>(
        "/paths/pick",
        "POST",
        { kind, initial_path: initial },
        controller.signal,
      );
      if (
        !controller.signal.aborted &&
        result.path &&
        latest.current.value === value &&
        !latest.current.disabled
      ) {
        latest.current.onChange(
          multiline ? appendPath(value, result.path) : result.path,
        );
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError((reason as Error).message);
    } finally {
      if (!controller.signal.aborted) {
        setSelecting(false);
        pending.current = null;
      }
    }
  }
  const action =
    kind === "folder" ? (multiline ? "添加文件夹" : "选择文件夹") : "选择文件";
  const control = {
    id,
    value,
    placeholder,
    disabled: disabled || selecting,
    onChange: /* 手动输入仍沿用相同的业务回调 */ (
      event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => {
      setError("");
      onChange(event.target.value);
    },
  };
  return (
    <div className={`path-field ${multiline ? "path-field-multiple" : ""}`}>
      <label htmlFor={id}>{label}</label>
      <div className="path-control">
        {multiline ? (
          <textarea {...control} rows={3} />
        ) : (
          <input {...control} />
        )}
        <button
          type="button"
          disabled={disabled || selecting}
          onClick={browse}
          aria-label={`${label}：${action}`}
          title={action}
        >
          {selecting ? (
            <LoaderCircle size={17} className="spin" />
          ) : kind === "folder" ? (
            <FolderOpen size={17} />
          ) : (
            <FileSearch size={17} />
          )}
          <span>{selecting ? "选择中…" : action}</span>
        </button>
      </div>
      {error && (
        <p className="path-picker-error" role="status">
          {error}
        </p>
      )}
    </div>
  );
}
