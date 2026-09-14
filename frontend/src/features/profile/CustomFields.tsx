import { Trash2 } from "lucide-react";
import type { CustomInfoField } from "../../shared/types";
import { VisibilityButton } from "./VisibilityField";

/** 自定义名称与内容沿用紧凑字段布局，支持独立隐藏、恢复和删除。 */
export default function CustomFields({
  fields,
  scope,
  editing = true,
  disabled = false,
  onChange,
}: {
  fields: CustomInfoField[];
  scope: string;
  editing?: boolean;
  disabled?: boolean;
  onChange: (fields: CustomInfoField[]) => void;
}) {
  /** 根据稳定标识更新单项，保留其他自定义信息及其顺序。 */
  function updateField(field: CustomInfoField) {
    onChange(
      fields.map(
        /* 只替换本次操作的信息项。 */ (item) =>
          item.id === field.id ? field : item,
      ),
    );
  }
  return (
    <>
      {fields.map(
        /* 将每项自定义信息放在固定字段之后。 */ (field, index) => (
          <div
            className="visibility-field custom-info-field"
            key={field.id}
            data-hidden={!field.visible || undefined}
          >
            <input
              className="custom-field-name"
              aria-label={`${scope}自定义信息 ${index + 1} 名称`}
              title={field.label}
              placeholder="信息名称"
              value={field.label}
              maxLength={50}
              readOnly={!editing || disabled}
              autoFocus={editing && !field.label}
              onChange={
                /* 支持直接修改自定义信息名称。 */ (event) =>
                  updateField({ ...field, label: event.target.value })
              }
            />
            <div className="field-control">
              <input
                aria-label={`${scope}自定义信息 ${index + 1} 内容`}
                placeholder={editing ? "填写内容" : "未填写"}
                value={field.value}
                maxLength={1000}
                readOnly={!editing || disabled}
                onChange={
                  /* 内容与名称一并进入当前资料草稿。 */ (event) =>
                    updateField({ ...field, value: event.target.value })
                }
              />
              <VisibilityButton
                label={field.label || `${scope}自定义信息 ${index + 1}`}
                hidden={!field.visible}
                disabled={!editing || disabled}
                onToggle={
                  /* 隐藏时保留自定义内容。 */ () =>
                    updateField({ ...field, visible: !field.visible })
                }
              />
              <button
                type="button"
                className="icon-button danger-hover"
                aria-label={`删除${field.label || `${scope}自定义信息 ${index + 1}`}`}
                disabled={!editing || disabled}
                onClick={
                  /* 删除当前自定义信息，其他字段保持原状。 */ () =>
                    onChange(
                      fields.filter(
                        /* 按稳定标识移除。 */ (item) => item.id !== field.id,
                      ),
                    )
                }
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ),
      )}
    </>
  );
}
