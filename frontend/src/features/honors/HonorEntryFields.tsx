import { Plus } from "lucide-react";
import type { SectionEntry } from "../../shared/types";
import { defaultLabel, hasDefault } from "../profile/defaults/model";
import CustomFields from "../profile/CustomFields";
import VisibilityField from "../profile/VisibilityField";
import {
  honorFieldHidden,
  honorFieldValue,
  isHonorCustomField,
  updateHonorField,
} from "./entry";
import { CATEGORIES, HONOR_FIELDS, type HonorField } from "./fields";

const PRIMARY = HONOR_FIELDS.filter(
  /* 默认界面只展示名称和日期 */ (field) =>
    field.key === "name" || field.key === "date",
);
const OPTIONAL = HONOR_FIELDS.filter(
  /* 其他资料保留为可展开、独立显隐的字段 */ (field) =>
    field.key !== "name" && field.key !== "date",
);

/** 在个人信息中使用与荣誉库一致的字段；折叠状态不改变简历显隐 */
export default function HonorEntryFields({
  entry,
  idPrefix,
  scope,
  editing,
  saving,
  expanded,
  onExpanded,
  onChange,
  onAddInfo,
  linked = false,
  showName = true,
}: {
  entry: SectionEntry;
  idPrefix: string;
  scope: string;
  editing: boolean;
  saving: boolean;
  expanded: boolean;
  onExpanded: (expanded: boolean) => void;
  onChange: (entry: SectionEntry) => void;
  onAddInfo?: () => void;
  linked?: boolean;
  showName?: boolean;
}) {
  const custom = entry.custom_fields.filter(
    /* 固定字段由上方的专用控件编辑 */ (field) => !isHonorCustomField(field),
  );
  const visibleCount =
    OPTIONAL.filter(
      /* 提示已进入成品的附加字段以免折叠后误以为全部隐藏 */ (field) =>
        !honorFieldHidden(entry, field.key) &&
        honorFieldValue(entry, field.key).trim(),
    ).length +
    custom.filter(
      /* 自定义资料同样计入显示提示 */ (field) =>
        field.visible && field.label.trim() && field.value.trim(),
    ).length;

  /** 同一字段使用统一标签、长度限制和更新逻辑 */
  function renderField(field: HonorField) {
    const fieldId =
      (
        {
          name: "title",
          issuer: "subtitle",
          date: "period",
          description: "details",
        } as Record<string, string>
      )[field.key] ?? `honor-field:${field.key}`;
    if (!hasDefault(entry.field_definitions, fieldId)) return null;
    const id = `${idPrefix}-${field.key}`;
    const full =
      entry.custom_fields.length >= 25 &&
      !["name", "date", "issuer", "description"].includes(field.key) &&
      !entry.custom_fields.some(
        /* 满额时已有字段仍允许编辑 */ (item) =>
          item.id === `honor-field:${field.key}`,
      );
    const disabled = !editing || saving || full;
    const value = honorFieldValue(entry, field.key);
    /** 编辑当前表单草稿；由上层统一保存内容与显示设置 */
    function updateValue(value: string) {
      onChange(updateHonorField(entry, field.key, { value }));
    }
    return (
      <VisibilityField
        key={field.key}
        id={id}
        label={defaultLabel(entry.field_definitions, fieldId, field.label)}
        hidden={honorFieldHidden(entry, field.key)}
        disabled={disabled}
        onToggle={
          /* 显示和隐藏只影响简历；保留信息原文 */ () =>
            onChange(
              updateHonorField(entry, field.key, {
                hidden: !honorFieldHidden(entry, field.key),
              }),
            )
        }
      >
        {field.key === "category" ? (
          <select
            id={id}
            value={value}
            disabled={disabled || linked}
            onChange={
              /* 分类名称与库中一致 */ (event) =>
                updateValue(event.target.value)
            }
          >
            {!value && <option value="">未填写</option>}
            {CATEGORIES.map(
              /* 分类选项共用同一份枚举 */ (category) => (
                <option key={category}>{category}</option>
              ),
            )}
          </select>
        ) : field.key === "description" ? (
          <textarea
            id={id}
            rows={2}
            maxLength={field.max}
            value={value}
            readOnly={disabled || linked}
            placeholder={editing ? field.placeholder : "未填写"}
            onChange={
              /* 保留说明中的换行 */ (event) => updateValue(event.target.value)
            }
          />
        ) : (
          <input
            id={id}
            maxLength={field.max}
            value={value}
            readOnly={disabled || linked}
            placeholder={
              full
                ? "信息项已满，请先删除自定义信息"
                : editing
                  ? field.placeholder
                  : "未填写"
            }
            onChange={
              /* 编辑字段值不会自动打开显隐 */ (event) =>
                updateValue(event.target.value)
            }
          />
        )}
      </VisibilityField>
    );
  }

  return (
    <div className="honor-entry-fields">
      <div className="profile-fields compact-fields">
        {PRIMARY.filter(
          /* 只读卡片已在标题中显示荣誉名称；编辑表单仍提供完整字段 */ (
            field,
          ) => showName || field.key !== "name",
        ).map(renderField)}
      </div>
      <details
        className="honor-entry-more"
        open={expanded}
        onToggle={
          /* 展开更多信息只改变表单展示 */ (event) =>
            onExpanded(event.currentTarget.open)
        }
      >
        <summary>
          其他荣誉信息
          {visibleCount ? ` · ${visibleCount} 项用于简历` : ""}
        </summary>
        {onAddInfo && (
          <div className="honor-entry-options">
            <button
              type="button"
              disabled={!editing || saving || custom.length >= 20}
              onClick={onAddInfo}
            >
              <Plus size={14} />
              添加信息
            </button>
          </div>
        )}
        <div className="profile-fields compact-fields">
          {OPTIONAL.map(renderField)}
          <CustomFields
            fields={custom}
            definitions={entry.field_definitions}
            editing={editing}
            disabled={saving}
            scope={scope}
            onChange={
              /* 编辑自定义资料时保留全部固定荣誉字段 */ (fields) =>
                onChange({
                  ...entry,
                  custom_fields: [
                    ...entry.custom_fields.filter(isHonorCustomField),
                    ...fields,
                  ],
                })
            }
          />
        </div>
      </details>
    </div>
  );
}
