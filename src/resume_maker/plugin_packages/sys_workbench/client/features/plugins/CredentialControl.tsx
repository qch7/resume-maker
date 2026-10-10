import { useEffect, useRef, useState } from "react";

/** 密码只提交到凭据入口，表单草稿只接收宿主生成的引用 */
export default function CredentialControl({
  id,
  field,
  label,
  reference,
  disabled,
  onChange,
  onPending,
  onSave,
}: {
  id: string;
  field: string;
  label: string;
  reference: string;
  disabled: boolean;
  onChange: (reference: string) => void;
  onPending?: (pending: boolean) => void;
  onSave: (field: string, secret: string) => Promise<string>;
}) {
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pendingCallback = useRef(onPending);
  pendingCallback.current = onPending;
  useEffect(() => () => pendingCallback.current?.(false), []);
  /** 保存创建新引用，旧配置在候选计划通过前仍能借用原凭据 */
  async function save() {
    setBusy(true);
    setError("");
    try {
      const reference = await onSave(field, secret);
      onChange(reference);
      setSecret("");
      onPending?.(false);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="plugin-credential-control">
      <span className="plugin-credential-status">
        {reference ? "已配置凭据" : "尚未配置"}
      </span>
      <div className="plugin-input-action">
        <input
          id={id}
          aria-label={`${label} 密码`}
          type="password"
          autoComplete="new-password"
          value={secret}
          disabled={disabled || busy}
          placeholder={reference ? "输入新密钥以替换" : "输入密钥"}
          onChange={(event) => {
            setSecret(event.target.value);
            onPending?.(!!event.target.value);
          }}
        />
        <button
          disabled={disabled || busy || !secret}
          onClick={() => void save()}
        >
          {busy ? "保存中…" : "保存凭据"}
        </button>
        {secret && (
          <button
            disabled={busy}
            onClick={() => {
              setSecret("");
              onPending?.(false);
            }}
          >
            放弃输入
          </button>
        )}
      </div>
      <small>保存后查看变更并应用；密码不会进入普通配置。</small>
      {error && (
        <small className="plugin-config-error" role="alert">
          {error}
        </small>
      )}
    </div>
  );
}
