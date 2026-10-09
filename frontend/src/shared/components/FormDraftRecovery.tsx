import type { ReactNode } from "react";
import type { useFormDraft } from "../hooks/useFormDraft";

/** 展示可核对的最新资料和恢复副本，明确选择后才允许继续保存 */
export default function FormDraftRecovery<T>({
  form,
  renderValue,
  disabled = false,
}: {
  form: ReturnType<typeof useFormDraft<T>>;
  renderValue: (value: T) => ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className="form-draft-recovery">
      {form.conflict && (
        <div role="alert" className="warning">
          <p>
            {form.baseline === null
              ? "旧草稿缺少读取基线，请对照最新资料决定保留的内容。"
              : "资料已在其他窗口修改，本页输入已保留。请选择载入最新资料或合并后继续编辑。"}
          </p>
          <div className="actions">
            <button
              type="button"
              disabled={disabled}
              onClick={() => form.resolve("latest")}
            >
              载入最新资料
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => form.resolve("merge")}
            >
              {form.baseline === null ? "以本页内容继续编辑" : "合并后继续编辑"}
            </button>
          </div>
          <details>
            <summary>查看最新资料</summary>
            {renderValue(form.latest)}
          </details>
        </div>
      )}
      {form.notice && <p role="status">{form.notice}</p>}
      {!form.conflict && form.notice && (
        <details>
          <summary>对照最新资料</summary>
          {renderValue(form.latest)}
        </details>
      )}
      {form.copies.length > 0 && (
        <details>
          <summary>恢复副本（{form.copies.length}）</summary>
          {form.copies.map((copy, index) => (
            <details key={index}>
              <summary>副本 {index + 1}</summary>
              {renderValue(copy.value)}
              <button
                type="button"
                disabled={disabled}
                onClick={() => form.recover(index)}
              >
                恢复副本 {index + 1}
              </button>
            </details>
          ))}
        </details>
      )}
    </div>
  );
}
