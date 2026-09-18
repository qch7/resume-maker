import { FilePenLine, LoaderCircle, Plus, Save, Trash2 } from "lucide-react";
import { useState } from "react";
import { isSkillsSection } from "../workflow/profile";
import type {
  ResumeSection,
  SectionEntry,
  SectionEntryField,
} from "../../shared/types";
import { newCustomField, newEntry, toggleHiddenField } from "./document";
import { sameSectionEntry } from "./comparison";
import { defaultLabel, hasDefault } from "./defaults/model";
import CustomFields from "./CustomFields";
import VisibilityField, { VisibilityButton } from "./VisibilityField";
import {
  isHonorEntry,
  isHonorSection,
  isHonorCustomField,
} from "../honors/entry";
import HonorEntryFields from "../honors/HonorEntryFields";
import type { HonorSource } from "../../shared/types/honors";

/** 在教育背景、课程、证书或自定义栏目中增删条目并编辑结构化字段 */
export default function SectionEditor({
  section,
  parent,
  savedSection,
  savedVersion,
  onSaveEntry,
  onChange,
  honors = [],
  onEditHonor,
  onHonors,
  onSort,
}: {
  section: ResumeSection;
  parent?: ResumeSection;
  savedSection?: ResumeSection;
  savedVersion?: number;
  onSaveEntry: (sectionId: string, entryId: string) => Promise<void>;
  onChange: (section: ResumeSection) => void;
  honors?: HonorSource[];
  onEditHonor?: (id: string, sectionId: string, entry: SectionEntry) => void;
  onHonors: () => void;
  onSort: (sectionId: string) => void;
}) {
  /** 替换单条内容并保留条目顺序 */
  function updateEntry(entry: SectionEntry) {
    onChange({
      ...section,
      entries: section.entries.map(
        /* 按标识定位正在编辑的条目 */ (item) =>
          item.id === entry.id ? entry : item,
      ),
    });
  }
  const education = section.kind === "education";
  const honorSection = isHonorSection(section);
  return (
    <section
      className={`profile-card ${parent ? "profile-child" : ""}`}
      aria-label={`${section.title}资料`}
      data-guide={
        education
          ? "personal-education"
          : isSkillsSection(section)
            ? "personal-skills"
            : undefined
      }
      tabIndex={-1}
    >
      <div className="section-heading">
        <h2>{section.title}</h2>
        <span className="tag">
          {parent ? `${parent.title} / 子栏目` : "大栏目"}
        </span>
        {(!section.visible || parent?.visible === false) && (
          <span className="tag warning-tag">已隐藏</span>
        )}
        <div className="row profile-section-actions">
          <button
            className="text-button"
            disabled={!honorSection && section.entries.length >= 100}
            onClick={
              /* 证书统一从荣誉库添加；其他栏目继续创建空条目 */ () => {
                if (honorSection) onHonors();
                else
                  onChange({
                    ...section,
                    entries: [
                      ...section.entries,
                      newEntry(section.field_definitions),
                    ],
                  });
              }
            }
          >
            <Plus size={14} />
            {honorSection
              ? "添加证书"
              : education
                ? "添加教育经历"
                : "添加条目"}
          </button>
          <button
            className="text-button"
            aria-label={`${section.title}排序`}
            title="到栏目编排调整顺序"
            onClick={
              /* 所有栏目共用编排页排序；新建栏目自动具备同一入口 */ () =>
                onSort(section.id)
            }
          >
            排序
          </button>
        </div>
      </div>
      {!section.entries.length && (
        <p className="subtle profile-empty">
          {honorSection
            ? "点击“添加证书”，从荣誉证书板块上传或选择证书加入简历。"
            : education
              ? "添加学校、专业、学历及在校时间。"
              : `添加${section.title}内容，支持多条记录与多行描述。`}
        </p>
      )}
      {section.entries.map(
        /* 每条资料具有独立且稳定的编辑身份 */ (entry, index) => (
          <EntryEditor
            source={honors.find(
              /* 来源身份与所在栏目名称无关 */ (item) =>
                item.reviewed && entry.id === `honor:${item.id}`,
            )}
            onEditHonor={onEditHonor}
            key={entry.id}
            section={section}
            entry={entry}
            index={index}
            savedEntry={savedSection?.entries.find(
              /* 以稳定标识匹配保存记录 */ (item) => item.id === entry.id,
            )}
            savedVersion={savedVersion}
            onSaveEntry={onSaveEntry}
            updateEntry={updateEntry}
            onChange={onChange}
          />
        ),
      )}
    </section>
  );
}

/** 每条资料独立维护编辑会话；保存成功回到只读；失败保留原输入 */
function EntryEditor({
  section,
  entry,
  index,
  savedEntry,
  savedVersion,
  onSaveEntry,
  updateEntry,
  onChange,
  source,
  onEditHonor,
}: {
  section: ResumeSection;
  entry: SectionEntry;
  index: number;
  savedEntry?: SectionEntry;
  savedVersion?: number;
  onSaveEntry: (sectionId: string, entryId: string) => Promise<void>;
  updateEntry: (entry: SectionEntry) => void;
  onChange: (section: ResumeSection) => void;
  source?: HonorSource;
  onEditHonor?: (id: string, sectionId: string, entry: SectionEntry) => void;
}) {
  const [editRequest, setEditRequest] = useState<{ version?: number } | null>(
    null,
  );
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [honorExpanded, setHonorExpanded] = useState(false);
  const honor = isHonorEntry(entry, section);
  const linked = !!source && !!onEditHonor;
  const editing =
    (editRequest !== null && editRequest.version === savedVersion) ||
    !sameSectionEntry(entry, savedEntry) ||
    !savedEntry;
  /** 只有服务器确认成功才结束本条编辑会话 */
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
        {honor ? (
          <h3 className="profile-entry-title">
            {entry.title.trim() || "未命名荣誉"}
          </h3>
        ) : (
          <span className="subtle">
            {education ? "教育经历" : "条目"} {index + 1}
          </span>
        )}
        <div className="row">
          <button
            aria-label={`编辑${section.title}条目 ${index + 1}`}
            disabled={(!linked && editing) || saving}
            onClick={
              /* 关联荣誉在一个表单中编辑内容与显示设置 */ () => {
                if (source && onEditHonor) {
                  onEditHonor(source.id, section.id, entry);
                  return;
                }
                setEditRequest({ version: savedVersion });
                setSaveError("");
              }
            }
          >
            <FilePenLine size={14} />
            编辑
          </button>
          {!linked && (
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
          )}
          {!linked && (
            <button
              className="text-button"
              aria-label={`为${section.title}条目 ${index + 1}添加信息`}
              disabled={
                saving ||
                entry.custom_fields.filter(
                  /* 固定荣誉资料不占用用户的二十个自定义名额 */ (field) =>
                    !honor || !isHonorCustomField(field),
                ).length >= 20
              }
              onClick={
                /* 添加字段时自动进入本条编辑 */ () => {
                  setEditRequest({ version: savedVersion });
                  setSaveError("");
                  if (honor) setHonorExpanded(true);
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
          )}
          {!linked && (
            <VisibilityButton
              label={`${section.title}条目 ${index + 1}`}
              hidden={entry.visible === false}
              disabled={!editing || saving}
              onToggle={
                /* 整条隐藏不删除正文或各字段的显隐设置 */ () =>
                  updateEntry({
                    ...entry,
                    visible: entry.visible === false,
                  })
              }
            />
          )}
          <button
            className="icon-button danger-hover"
            aria-label={`删除${section.title}条目 ${index + 1}`}
            disabled={saving}
            onClick={
              /* 删除当前资料条目 */ () =>
                onChange({
                  ...section,
                  entries: section.entries.filter(
                    /* 保留其他条目 */ (item) => item.id !== entry.id,
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
      {honor ? (
        <HonorEntryFields
          showName={!linked && editing}
          linked={!!source}
          entry={entry}
          idPrefix={`entry-${section.id}-${entry.id}`}
          scope={`${section.title}条目 ${index + 1}`}
          editing={!linked && editing}
          saving={saving}
          expanded={honorExpanded}
          onExpanded={setHonorExpanded}
          onChange={updateEntry}
        />
      ) : (
        <>
          <div className="profile-fields compact-fields">
            {fields
              .filter(
                /* 条目使用所属栏目的默认字段结构 */ (field) =>
                  hasDefault(
                    entry.field_definitions ?? section.field_definitions,
                    field.key,
                  ),
              )
              .map(
                /* 栏目字段共用独立输入与显隐开关 */ (field) => (
                  <VisibilityField
                    key={field.key}
                    id={`entry-${section.id}-${entry.id}-${field.key}`}
                    label={defaultLabel(
                      entry.field_definitions ?? section.field_definitions,
                      field.key,
                      field.label,
                    )}
                    hidden={entry.hidden_fields.includes(field.key)}
                    disabled={!editing || saving}
                    onToggle={
                      /* 只切换当前字段；保持原有资料值 */ () =>
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
                        /* 更新本条资料的对应字段 */ (event) =>
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
              definitions={entry.field_definitions ?? section.field_definitions}
              editing={editing}
              disabled={saving}
              scope={`${section.title}条目 ${index + 1}`}
              onChange={
                /* 每条经历的自定义字段独立保存且不串到其他条目 */ (
                  custom_fields,
                ) => updateEntry({ ...entry, custom_fields })
              }
            />
          </div>
          {hasDefault(
            entry.field_definitions ?? section.field_definitions,
            "details",
          ) && (
            <VisibilityField
              id={`entry-${section.id}-${entry.id}-details`}
              label={defaultLabel(
                entry.field_definitions ?? section.field_definitions,
                "details",
                education ? "补充说明" : "详细内容",
              )}
              hidden={entry.hidden_fields.includes("details")}
              disabled={!editing || saving}
              onToggle={
                /* 正文也可独立隐藏和恢复 */ () =>
                  updateEntry({
                    ...entry,
                    hidden_fields: toggleHiddenField(
                      entry.hidden_fields,
                      "details",
                    ),
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
                  /* 同步多行正文 */ (event) =>
                    updateEntry({ ...entry, details: event.target.value })
                }
              />
            </VisibilityField>
          )}
        </>
      )}
    </div>
  );
}
