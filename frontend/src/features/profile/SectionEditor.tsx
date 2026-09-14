import {
  ArrowDown,
  ArrowUp,
  FilePenLine,
  LoaderCircle,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import type {
  ResumeSection,
  SectionEntry,
  SectionEntryField,
} from "../../shared/types";
import { newCustomField, newEntry, toggleHiddenField } from "./document";
import { sameSectionEntry } from "./comparison";
import CustomFields from "./CustomFields";
import VisibilityField, { VisibilityButton } from "./VisibilityField";

/** 在教育背景、课程、证书或自定义栏目中增删条目，并编辑结构化字段。 */
export default function SectionEditor({
  section,
  parent,
  savedSection,
  savedVersion,
  onSaveEntry,
  onChange,
}: {
  section: ResumeSection;
  parent?: ResumeSection;
  savedSection?: ResumeSection;
  savedVersion?: number;
  onSaveEntry: (sectionId: string, entryId: string) => Promise<void>;
  onChange: (section: ResumeSection) => void;
}) {
  /** 替换单条内容并保留条目顺序。 */
  function updateEntry(entry: SectionEntry) {
    onChange({
      ...section,
      entries: section.entries.map(
        /* 按标识定位正在编辑的条目。 */ (item) =>
          item.id === entry.id ? entry : item,
      ),
    });
  }
  /** 在当前栏目中调整条目顺序。 */
  function moveEntry(from: number, to: number) {
    const entries = [...section.entries];
    const [entry] = entries.splice(from, 1);
    entries.splice(to, 0, entry);
    onChange({ ...section, entries });
  }
  const education = section.kind === "education";
  return (
    <section
      className={`profile-card ${parent ? "profile-child" : ""}`}
      aria-label={`${section.title}资料`}
    >
      <div className="section-heading">
        <h2>{section.title}</h2>
        <span className="tag">
          {parent ? `${parent.title} / 子栏目` : "大栏目"}
        </span>
        {(!section.visible || parent?.visible === false) && (
          <span className="tag warning-tag">已隐藏</span>
        )}
        <button
          className="text-button"
          disabled={section.entries.length >= 100}
          onClick={
            /* 在栏目末尾添加空条目。 */ () =>
              onChange({
                ...section,
                entries: [...section.entries, newEntry()],
              })
          }
        >
          <Plus size={14} />
          {education ? "添加教育经历" : "添加条目"}
        </button>
      </div>
      {!section.entries.length && (
        <p className="subtle profile-empty">
          {education
            ? "添加学校、专业、学历及在校时间。"
            : `添加${section.title}内容，支持多条记录与多行描述。`}
        </p>
      )}
      {section.entries.map(
        /* 每条资料具有独立且稳定的编辑身份。 */ (entry, index) => (
          <EntryEditor
            key={entry.id}
            section={section}
            entry={entry}
            index={index}
            savedEntry={savedSection?.entries.find(
              /* 以稳定标识匹配保存记录。 */ (item) => item.id === entry.id,
            )}
            savedVersion={savedVersion}
            onSaveEntry={onSaveEntry}
            updateEntry={updateEntry}
            moveEntry={moveEntry}
            onChange={onChange}
          />
        ),
      )}
    </section>
  );
}

/** 每条资料独立维护编辑会话，保存成功回到只读，失败保留原输入。 */
function EntryEditor({
  section,
  entry,
  index,
  savedEntry,
  savedVersion,
  onSaveEntry,
  updateEntry,
  moveEntry,
  onChange,
}: {
  section: ResumeSection;
  entry: SectionEntry;
  index: number;
  savedEntry?: SectionEntry;
  savedVersion?: number;
  onSaveEntry: (sectionId: string, entryId: string) => Promise<void>;
  updateEntry: (entry: SectionEntry) => void;
  moveEntry: (from: number, to: number) => void;
  onChange: (section: ResumeSection) => void;
}) {
  const [editRequest, setEditRequest] = useState<{ version?: number } | null>(
    null,
  );
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const editing =
    (editRequest !== null && editRequest.version === savedVersion) ||
    !sameSectionEntry(entry, savedEntry) ||
    !savedEntry;
  /** 只有服务器确认成功才结束本条编辑会话。 */
  async function saveEntry() {
    if (saving) return;
    setSaving(true);
    setSaveError("");
    try {
      await onSaveEntry(section.id, entry.id);
      setEditRequest(null);
    } catch (error) {
      setSaveError((error as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const education = section.kind === "education";
  const fields: {
    key: SectionEntryField;
    label: string;
    maxLength: number;
    placeholder: string;
  }[] = [
    {
      key: "title",
      label: education ? "学校名称" : "标题",
      maxLength: 300,
      placeholder: education
        ? "如：杭州电子科技大学"
        : "如：竞赛名称、证书名称、技能类别（选填）",
    },
    {
      key: "subtitle",
      label: education ? "专业 / 学历" : "补充信息",
      maxLength: 500,
      placeholder: education
        ? "如：计算机科学与技术 · 本科"
        : "如：级别、颁发机构（选填）",
    },
    {
      key: "period",
      label: education ? "在校时间" : "时间",
      maxLength: 100,
      placeholder: "如：2024.09 – 2028.06",
    },
  ];
  return (
    <div
      className="profile-entry"
      aria-label={`${section.title}条目 ${index + 1}`}
      data-hidden={entry.visible === false || undefined}
    >
      <div className="section-heading">
        <span className="subtle">
          {education ? "教育经历" : "条目"} {index + 1}
        </span>
        <div className="row">
          <button
            aria-label={`编辑${section.title}条目 ${index + 1}`}
            disabled={editing || saving}
            onClick={
              /* 明确进入本条资料的编辑状态。 */ () => {
                setEditRequest({ version: savedVersion });
                setSaveError("");
              }
            }
          >
            <FilePenLine size={14} />
            编辑
          </button>
          <button
            className="primary"
            aria-label={`保存${section.title}条目 ${index + 1}`}
            disabled={!editing || saving}
            onClick={saveEntry}
          >
            {saving ? (
              <LoaderCircle className="spin" size={14} />
            ) : (
              <Save size={14} />
            )}
            {saving ? "保存中…" : "保存"}
          </button>
          <button
            className="text-button"
            aria-label={`为${section.title}条目 ${index + 1}添加信息`}
            disabled={saving || entry.custom_fields.length >= 20}
            onClick={
              /* 添加字段时自动进入本条编辑。 */ () => {
                setEditRequest({ version: savedVersion });
                setSaveError("");
                updateEntry({
                  ...entry,
                  custom_fields: [...entry.custom_fields, newCustomField()],
                });
              }
            }
          >
            <Plus size={14} />
            添加条目
          </button>
          <VisibilityButton
            label={`${section.title}条目 ${index + 1}`}
            hidden={entry.visible === false}
            disabled={!editing || saving}
            onToggle={
              /* 整条隐藏不删除正文或各字段的显隐设置。 */ () =>
                updateEntry({
                  ...entry,
                  visible: entry.visible === false,
                })
            }
          />
          <button
            className="icon-button"
            aria-label={`上移${section.title}条目 ${index + 1}`}
            disabled={saving || index === 0}
            onClick={/* 上移到相邻位置。 */ () => moveEntry(index, index - 1)}
          >
            <ArrowUp size={14} />
          </button>
          <button
            className="icon-button"
            aria-label={`下移${section.title}条目 ${index + 1}`}
            disabled={saving || index === section.entries.length - 1}
            onClick={/* 下移到相邻位置。 */ () => moveEntry(index, index + 1)}
          >
            <ArrowDown size={14} />
          </button>
          <button
            className="icon-button danger-hover"
            aria-label={`删除${section.title}条目 ${index + 1}`}
            disabled={saving}
            onClick={
              /* 删除当前资料条目。 */ () =>
                onChange({
                  ...section,
                  entries: section.entries.filter(
                    /* 保留其他条目。 */ (item) => item.id !== entry.id,
                  ),
                })
            }
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {saveError && (
        <p className="warning" role="alert">
          {saveError}
        </p>
      )}
      <div className="profile-fields compact-fields">
        {fields.map(
          /* 栏目字段共用独立输入与显隐开关。 */ (field) => (
            <VisibilityField
              key={field.key}
              id={`entry-${section.id}-${entry.id}-${field.key}`}
              label={field.label}
              hidden={entry.hidden_fields.includes(field.key)}
              disabled={!editing || saving}
              onToggle={
                /* 只切换当前字段，保持原有资料值。 */ () =>
                  updateEntry({
                    ...entry,
                    hidden_fields: toggleHiddenField(
                      entry.hidden_fields,
                      field.key,
                    ),
                  })
              }
            >
              <input
                id={`entry-${section.id}-${entry.id}-${field.key}`}
                readOnly={!editing || saving}
                maxLength={field.maxLength}
                value={entry[field.key]}
                placeholder={editing ? field.placeholder : "未填写"}
                onChange={
                  /* 更新本条资料的对应字段。 */ (event) =>
                    updateEntry({
                      ...entry,
                      [field.key]: event.target.value,
                    })
                }
              />
            </VisibilityField>
          ),
        )}
        <CustomFields
          fields={entry.custom_fields}
          editing={editing}
          disabled={saving}
          scope={`${section.title}条目 ${index + 1}`}
          onChange={
            /* 每条经历的自定义字段独立保存，不串到其他条目。 */ (
              custom_fields,
            ) => updateEntry({ ...entry, custom_fields })
          }
        />
      </div>
      <VisibilityField
        id={`entry-${section.id}-${entry.id}-details`}
        label={education ? "补充说明" : "详细内容"}
        hidden={entry.hidden_fields.includes("details")}
        disabled={!editing || saving}
        onToggle={
          /* 正文也可独立隐藏和恢复。 */ () =>
            updateEntry({
              ...entry,
              hidden_fields: toggleHiddenField(entry.hidden_fields, "details"),
            })
        }
      >
        <textarea
          id={`entry-${section.id}-${entry.id}-details`}
          readOnly={!editing || saving}
          rows={2}
          maxLength={10000}
          value={entry.details}
          placeholder={
            !editing
              ? "未填写"
              : education
                ? "研究方向、排名或其他补充信息；主修课程可在下方子栏目填写。"
                : "填写具体内容，支持换行；只填写正文也可以。"
          }
          onChange={
            /* 同步多行正文。 */ (event) =>
              updateEntry({ ...entry, details: event.target.value })
          }
        />
      </VisibilityField>
    </div>
  );
}
