import { useId } from "react";
import CredentialControl from "./CredentialControl";
import {
  changeConfigField,
  changeConfigJson,
  configDraftError,
  configFields,
  configInput,
  configRange,
  configResetPending,
  configSource,
  configValue,
  draftConfigValue,
  resetConfigField,
  undoConfigReset,
  type ConfigDraft,
  type ConfigField,
  type ConfigSchema,
  type FieldInput,
} from "./configurationForm";

interface Props {
  plugin?: string;
  credentialFields?: Record<string, { title: string; purpose: string }>;
  onCredentialPending?: (field: string, pending: boolean) => void;
  onSaveCredential?: (field: string, secret: string) => Promise<string>;
  title: string;
  schema: ConfigSchema;
  value: Record<string, unknown>;
  provenance: Record<string, string>;
  draft: ConfigDraft;
  disabled: boolean;
  preview?: {
    value: Record<string, unknown>;
    provenance: Record<string, string>;
  };
  onChange: (draft: ConfigDraft) => void;
}

interface ControlProps {
  id: string;
  label: string;
  field: ConfigField;
  input: FieldInput;
  disabled: boolean;
  onChange: (input: FieldInput) => void;
}

/** 字段类型决定控件，空值始终独立于空字符串和缺失值 */
function ConfigControl({
  id,
  label,
  field,
  input,
  disabled,
  onChange,
}: ControlProps) {
  const common = {
    id,
    "aria-label": label,
    "aria-invalid": !!input.error,
    "aria-describedby": `${id}-meta${input.error ? ` ${id}-error` : ""}`,
    disabled: disabled || field.schema.readOnly || input.nullValue,
  };
  if (field.kind === "boolean") {
    return (
      <input
        {...common}
        type="checkbox"
        checked={input.text === "true"}
        onChange={(event) => onChange({ text: String(event.target.checked) })}
      />
    );
  }
  if (field.kind === "enum") {
    return (
      <select
        {...common}
        value={input.text}
        onChange={(event) => onChange({ text: event.target.value })}
      >
        {input.text === "" && <option value="">未设置</option>}
        {field.schema.enum!.map((option, index) => (
          <option key={index} value={JSON.stringify(option)}>
            {option === null
              ? "空值"
              : typeof option === "string"
                ? option
                : JSON.stringify(option)}
          </option>
        ))}
      </select>
    );
  }
  if (field.kind === "json") {
    return (
      <textarea
        {...common}
        spellCheck={false}
        rows={3}
        value={input.text}
        onChange={(event) => onChange({ text: event.target.value })}
      />
    );
  }
  return (
    <input
      {...common}
      type={field.kind === "string" ? "text" : "number"}
      step={field.schema.multipleOf ?? (field.kind === "integer" ? 1 : "any")}
      min={field.schema.minimum}
      max={field.schema.maximum}
      value={input.text}
      placeholder={input.nullValue ? "空值" : "未设置"}
      onChange={(event) => onChange({ text: event.target.value })}
    />
  );
}

/** 配置值、来源和恢复操作在同一字段内显示，复杂结构保留高级编辑 */
export default function PluginConfigEditor({
  plugin,
  credentialFields = {},
  onCredentialPending,
  onSaveCredential,
  title,
  schema,
  value,
  provenance,
  draft,
  disabled,
  preview,
  onChange,
}: Props) {
  const prefix = useId();
  const fields = configFields(schema);
  const current = preview?.value ?? draftConfigValue(value, draft);
  const sources = preview?.provenance ?? provenance;
  const wholeReset = draft.edits.some(
    (edit) => edit.operation === "reset" && !edit.path.length,
  );
  const rawError =
    draft.json !== undefined ? configDraftError({ ...draft, fields: {} }) : "";
  const canResetAll =
    draft.json !== undefined ||
    Object.keys(draft.fields).length > 0 ||
    draft.edits.length > 0 ||
    Object.values(provenance).some(
      (source) => source === "workspace" || source === "startup",
    );
  return (
    <div className="plugin-config-editor">
      <div className="plugin-config-fields">
        {fields.map((field, index) => {
          const id = `${prefix}-${index}`;
          const pendingReset =
            !preview && configResetPending(draft, field.path);
          const input =
            (!preview && draft.fields[field.pointer]) ||
            configInput(field, configValue(current, field.path));
          const changed =
            !preview &&
            (draft.fields[field.pointer] !== undefined ||
              draft.json !== undefined ||
              draft.edits.some(
                (edit) =>
                  edit.operation === "set" &&
                  edit.path.every(
                    (key, position) => field.path[position] === key,
                  ),
              ));
          const source = pendingReset
            ? "待恢复"
            : changed
              ? "待应用"
              : configSource(sources[field.pointer]);
          const range = configRange(field.schema);
          const canReset =
            changed ||
            sources[field.pointer] === "workspace" ||
            sources[field.pointer] === "startup";
          return (
            <div
              key={field.pointer}
              className={`plugin-config-field${input.error ? " is-invalid" : ""}`}
            >
              <div className="plugin-config-field-heading">
                <label htmlFor={pendingReset ? undefined : id}>
                  {field.label}
                </label>
                <button
                  type="button"
                  disabled={
                    disabled ||
                    field.schema.readOnly ||
                    (!pendingReset && !canReset) ||
                    (pendingReset && wholeReset)
                  }
                  aria-label={`${title} ${field.label}${pendingReset ? "撤销重置" : "重置"}`}
                  onClick={() =>
                    onChange(
                      pendingReset
                        ? undoConfigReset(draft, field.path)
                        : resetConfigField(draft, field.path),
                    )
                  }
                >
                  {pendingReset ? "撤销" : "重置"}
                </button>
              </div>
              <div className="plugin-config-control">
                {pendingReset ? (
                  <span className="plugin-config-pending">待恢复</span>
                ) : plugin &&
                  onSaveCredential &&
                  field.path.length === 1 &&
                  credentialFields[field.path[0]] ? (
                  <CredentialControl
                    id={id}
                    field={field.path[0]}
                    label={credentialFields[field.path[0]].title}
                    reference={input.text}
                    disabled={disabled || !!rawError}
                    onChange={(reference) =>
                      onChange(
                        changeConfigField(draft, field, { text: reference }),
                      )
                    }
                    onPending={(pending) =>
                      onCredentialPending?.(field.path[0], pending)
                    }
                    onSave={onSaveCredential}
                  />
                ) : (
                  <ConfigControl
                    id={id}
                    label={`${title} ${field.label}`}
                    field={field}
                    input={input}
                    disabled={disabled || !!rawError}
                    onChange={(next) =>
                      onChange(changeConfigField(draft, field, next))
                    }
                  />
                )}
                {field.nullable && field.kind !== "enum" && !pendingReset && (
                  <label className="plugin-config-null">
                    <input
                      type="checkbox"
                      checked={!!input.nullValue}
                      disabled={disabled || field.schema.readOnly || !!rawError}
                      onChange={(event) =>
                        onChange(
                          changeConfigField(draft, field, {
                            ...input,
                            nullValue: event.target.checked,
                          }),
                        )
                      }
                    />
                    空值
                  </label>
                )}
              </div>
              <small id={`${id}-meta`} className="plugin-config-meta">
                {range && <span>{range}</span>}
                <span>{source}</span>
              </small>
              {input.error && !preview && (
                <small
                  id={`${id}-error`}
                  className="plugin-config-error"
                  role="alert"
                >
                  {input.error}
                </small>
              )}
            </div>
          );
        })}
      </div>
      <div className="plugin-config-actions">
        <button
          type="button"
          disabled={disabled || !canResetAll}
          onClick={() =>
            onChange(
              wholeReset
                ? undoConfigReset(draft, [])
                : resetConfigField(draft, []),
            )
          }
        >
          {wholeReset ? "撤销全部重置" : "全部重置"}
        </button>
      </div>
      <details className="plugin-config-json">
        <summary>高级 JSON</summary>
        <textarea
          aria-label={`${title} JSON 配置`}
          spellCheck={false}
          aria-invalid={!!rawError}
          disabled={disabled}
          value={
            preview
              ? JSON.stringify(current, null, 2)
              : (draft.json ?? JSON.stringify(current, null, 2))
          }
          onChange={(event) => onChange(changeConfigJson(event.target.value))}
        />
        {rawError && !preview && (
          <small className="plugin-config-error" role="alert">
            {rawError}
          </small>
        )}
      </details>
    </div>
  );
}
