import {
  ArrowDown,
  ArrowUp,
  FilePenLine,
  List,
  Plus,
  Save,
} from "lucide-react";
import { useState, type ChangeEvent } from "react";
import type {
  ExperienceField,
  DefaultField,
  Meta,
  ProjectVisibility,
} from "../../shared/types";
import { arrayMove } from "@dnd-kit/sortable";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import { projectBodyOrder } from "./bodyOrder";
import { defaultLabel, hasDefault } from "../profile/defaults/model";
import { projectDefaultView } from "../profile/defaults/projects";
import CustomFields from "../profile/CustomFields";
import { newCustomField } from "../profile/document";
import VisibilityField from "../profile/VisibilityField";
import { fieldVisible } from "./visibility";

const FIELDS: {
  key: ExperienceField;
  label: string;
  placeholder: string;
  limit: number;
}[] = [
  { key: "title", label: "项目标题", placeholder: "填写项目名称", limit: 200 },
  {
    key: "period",
    label: "参与时间",
    placeholder: "例如 2026.2 - 2026.4",
    limit: 200,
  },
  { key: "role", label: "担任角色", placeholder: "由本人填写", limit: 300 },
  {
    key: "stack",
    label: "技术栈",
    placeholder: "用顿号或逗号分隔",
    limit: 10000,
  },
  {
    key: "description",
    label: "项目描述",
    placeholder: "填写项目描述",
    limit: 10000,
  },
];

/** 项目文字作为版本草稿编辑，眼睛按钮独立修改当前简历的显示设置 */
export default function MetaEditor({
  value: original,
  definitions,
  onChange,
  onFinish,
  status,
  conflict,
  onReload,
  visibility: originalVisibility,
  onVisibility,
}: {
  value: Meta;
  definitions?: DefaultField[] | null;
  onChange: (value: Meta) => void;
  onFinish: () => Promise<void>;
  status: string;
  conflict: boolean;
  onReload: () => Promise<Meta | undefined>;
  visibility: ProjectVisibility;
  onVisibility: (value: ProjectVisibility) => void;
}) {
  const {
    value,
    visibility,
    error: defaultsError,
  } = projectDefaultView(original, originalVisibility, definitions);
  const [editing, setEditing] = useState(!value.description);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [stackText, setStackText] = useState(value.stack.join("、"));
  const custom = value.custom_fields ?? [];
  /** 保存当前草稿成功后退出编辑，失败时仍保留输入和错误提示 */
  async function finish() {
    setSaving(true);
    setError("");
    try {
      await onFinish();
      setEditing(false);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }
  /** 固定字段共用同一编辑和显隐控件，移动只改变外层条目位置 */
  function renderField(field: (typeof FIELDS)[number]) {
    const id = `project-meta-${field.key}`;
    const props = {
      id,
      readOnly: !editing || saving,
      value: field.key === "stack" ? stackText : value[field.key],
      placeholder: editing ? field.placeholder : "未填写",
      maxLength: field.limit,
      onChange: /* 将文本输入同步到草稿，技术栈保留未输完的分隔符 */ (
        event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
      ) => {
        const text = event.target.value;
        if (field.key === "stack") {
          setStackText(text);
          onChange({
            ...value,
            stack: text
              .split(/[、,，]/)
              .map(/* 清理每个技术名称的前后空白 */ (item) => item.trim())
              .filter(Boolean),
          });
        } else onChange({ ...value, [field.key]: text });
      },
    };
    return (
      <VisibilityField
        key={field.key}
        id={id}
        label={defaultLabel(definitions, field.key, field.label)}
        hidden={!fieldVisible(value, visibility, field.key)}
        onToggle={
          /* 隐藏只改变排版，保留原文供恢复和版本对照 */ () =>
            onVisibility({
              fields: {
                [field.key]: !fieldVisible(value, visibility, field.key),
              },
            })
        }
      >
        {field.key === "description" ? (
          <textarea {...props} rows={3} />
        ) : (
          <input {...props} />
        )}
      </VisibilityField>
    );
  }
  const order = projectBodyOrder(value, visibility).filter(
    /* 删除的默认字段不再参与表单排序 */ (key) =>
      key === "highlights" ||
      (key.startsWith("custom:")
        ? !key.startsWith("custom:default:") ||
          hasDefault(definitions, key.slice(7))
        : hasDefault(definitions, key)),
  );
  /** 正文顺序进入元信息草稿，项目标题和参与时间不进入移动列表 */
  function move(from: number, to: number) {
    if (from === to || to < 0 || to >= order.length) return;
    onChange({ ...value, body_order: arrayMove(order, from, to) });
  }
  /** 为排序操作提供字段名称，自定义信息改名后同步更新辅助说明 */
  function labelFor(key: (typeof order)[number]) {
    if (key === "highlights") return "项目亮点";
    if (key.startsWith("custom:"))
      return (
        custom.find(
          /* 使用稳定标识读取自定义名称 */ (field) =>
            `custom:${field.id}` === key,
        )?.label || "自定义条目"
      );
    return FIELDS.find(
      /* 读取固定字段的中文名称 */ (field) => field.key === key,
    )!.label;
  }
  return (
    <section
      className="profile-card project-info"
      aria-labelledby="project-info-title"
    >
      <div className="section-heading">
        <h2 id="project-info-title">基本信息</h2>
        <div className="personal-actions">
          <button
            disabled={editing || saving}
            aria-label="编辑项目基本信息"
            onClick={
              /* 进入编辑，保留所有未提交的字段值 */ () => setEditing(true)
            }
          >
            <FilePenLine size={15} />
            编辑
          </button>
          <button
            className="primary"
            disabled={!editing || saving}
            onClick={finish}
          >
            <Save size={15} />
            {saving ? "保存中…" : "完成编辑"}
          </button>
          <button
            disabled={saving || custom.length >= 20}
            onClick={
              /* 添加条目时自动进入编辑，新条目沿用个人信息的命名和显隐规则 */ () => {
                setEditing(true);
                onChange({
                  ...value,
                  custom_fields: [...custom, newCustomField()],
                });
              }
            }
          >
            <Plus size={15} />
            添加条目
          </button>
        </div>
      </div>
      <div className="profile-fields compact-fields project-info-fixed">
        {FIELDS.slice(0, 2)
          .filter(
            /* 标题和时间同样遵循默认项设置 */ (field) =>
              hasDefault(definitions, field.key),
          )
          .map(renderField)}
      </div>
      <div className="project-info-body" role="group" aria-label="项目内容顺序">
        <SortableList
          items={order.map(
            /* 排序标识不随字段改名而变化 */ (id) => ({
              id,
              label: labelFor(id),
            }),
          )}
          onMove={move}
        >
          {order.map(
            /* 每条资料单独成行，亮点占位栏控制整个亮点组的位置 */ (
              key,
              index,
            ) => {
              const field = FIELDS.find(
                /* 区分固定资料和自定义条目 */ (item) => item.key === key,
              );
              const customIndex = custom.findIndex(
                /* 定位对应的原始内容，排序不改写版本 */ (item) =>
                  `custom:${item.id}` === key,
              );
              const item = custom[customIndex];
              const label = labelFor(key);
              return (
                <SortableItem
                  key={key}
                  id={key}
                  label={label}
                  className="project-info-row"
                >
                  {
                    /* 将拖拽手柄和上下移动按钮放在字段右侧 */ (handle) => (
                      <>
                        <div className="project-info-field">
                          {field ? (
                            renderField(field)
                          ) : key === "highlights" ? (
                            <div className="project-highlights-placeholder">
                              <strong>
                                <List size={15} />
                                项目亮点
                              </strong>
                              <span className="subtle">在下方编辑和排序</span>
                            </div>
                          ) : (
                            <CustomFields
                              fields={[item]}
                              definitions={definitions}
                              scope="项目"
                              indexOffset={customIndex}
                              editing={editing}
                              disabled={saving}
                              visibility={visibility.custom_fields}
                              onToggleVisibility={
                                /* 自定义条目显隐仍只保存在当前简历中 */ (id) =>
                                  onVisibility({
                                    custom_fields: {
                                      [id]: !(
                                        visibility.custom_fields?.[id] ??
                                        item.visible
                                      ),
                                    },
                                  })
                              }
                              onChange={
                                /* 只更新当前条目并保留其位置 */ (fields) =>
                                  onChange({
                                    ...value,
                                    custom_fields: fields.length
                                      ? custom.map(
                                          /* 保留原始内容顺序，展示位置独立保存 */ (
                                            entry,
                                          ) =>
                                            entry.id === item.id
                                              ? fields[0]
                                              : entry,
                                        )
                                      : custom.filter(
                                          /* 删除内容时同步移除该条 */ (
                                            entry,
                                          ) => entry.id !== item.id,
                                        ),
                                  })
                              }
                            />
                          )}
                        </div>
                        <div className="project-info-order">
                          <button
                            className="icon-button"
                            aria-label={`上移${label}`}
                            title={`上移${label}`}
                            disabled={index === 0}
                            onClick={
                              /* 向上移动一位，随内容一起提交版本 */ () =>
                                move(index, index - 1)
                            }
                          >
                            <ArrowUp size={13} />
                          </button>
                          {handle}
                          <button
                            className="icon-button"
                            aria-label={`下移${label}`}
                            title={`下移${label}`}
                            disabled={index === order.length - 1}
                            onClick={
                              /* 向下移动一位，随内容一起提交版本 */ () =>
                                move(index, index + 1)
                            }
                          >
                            <ArrowDown size={13} />
                          </button>
                        </div>
                      </>
                    )
                  }
                </SortableItem>
              );
            },
          )}
        </SortableList>
      </div>
      {(error || defaultsError) && (
        <p className="warning" role="alert">
          {error || defaultsError}
        </p>
      )}
      {(status || conflict) && (
        <div className="actions project-info-status">
          {status && (
            <span className="subtle" role="status">
              {status}
            </span>
          )}
          {conflict && (
            <button
              onClick={
                /* 冲突时明确载入服务器草稿，同时恢复技术栈的文本表示 */ async () => {
                  const remote = await onReload();
                  if (remote) setStackText(remote.stack.join("、"));
                }
              }
            >
              载入服务器草稿
            </button>
          )}
        </div>
      )}
    </section>
  );
}
