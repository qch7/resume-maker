import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Save, X } from "lucide-react";
import { api, download } from "../../shared/lib/api";
import { loadLocal, storage } from "../../shared/lib/storage";
import HonorImage from "./HonorImage";
import {
  CATEGORIES,
  emptyHonor,
  isRecognizing,
  type Honor,
  type HonorFields,
} from "./model";

import { HONOR_FIELDS } from "./fields";
import type { SectionEntry } from "../../shared/types";
import HonorEntryFields from "./HonorEntryFields";
import { entryWithHonorFields, honorFieldsFromEntry } from "./entry";
import { newCustomField } from "../profile/document";
import { VisibilityButton } from "../profile/VisibilityField";

const FIELDS = HONOR_FIELDS.filter(
  /* 分类和多行说明使用各自的专用控件 */ (field) =>
    field.key !== "category" && field.key !== "description",
);
const CATEGORY = HONOR_FIELDS.find(
  /* 分类和个人信息使用同一份字段标签 */ (field) => field.key === "category",
)!;
const DESCRIPTION = HONOR_FIELDS.find(
  /* 多行说明的限制和提示保持一致 */ (field) => field.key === "description",
)!;

/** 对照原件核对识别结果，保留未保存表单并用版本号防止并发覆盖 */
export default function HonorEditor({
  honor,
  onClose,
  onSaved,
  resumeEntry,
  onSaveEntry,
  draftScope = "library",
}: {
  honor: Honor | null;
  onClose: () => void;
  onSaved: (honor: Honor) => void;
  resumeEntry?: SectionEntry;
  onSaveEntry?: (entry: SectionEntry) => Promise<void>;
  draftScope?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const initialFields =
    honor?.fields ??
    (resumeEntry ? honorFieldsFromEntry(resumeEntry) : emptyHonor());
  const draftKey = `rm.honor.draft.${draftScope}.${resumeEntry?.id ?? honor?.id ?? "new"}`;
  const cached = useRef(
    loadLocal<{
      fields: HonorFields;
      baseline: HonorFields;
      version: number;
      entry?: SectionEntry;
      sourceSaved: boolean;
    } | null>(draftKey, null),
  ).current;
  const [fields, setFields] = useState(cached?.fields ?? initialFields);
  const [baseline, setBaseline] = useState(cached?.baseline ?? initialFields);
  const [version, setVersion] = useState(
    cached?.version ?? honor?.version ?? 0,
  );
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [entry, setEntry] = useState(cached?.entry ?? resumeEntry);
  const [expanded, setExpanded] = useState(true);
  const [sourceSaved, setSourceSaved] = useState(cached?.sourceSaved ?? false);
  const [appliedRecognitionVersion, setAppliedRecognitionVersion] = useState<
    number | null
  >(null);
  const contentDirty = JSON.stringify(fields) !== JSON.stringify(baseline);
  const dirty =
    contentDirty || JSON.stringify(entry) !== JSON.stringify(resumeEntry);
  const recognizing = honor ? isRecognizing(honor) : false;
  useEffect(() => {
    if (dirty)
      storage.setItem(
        draftKey,
        JSON.stringify({ fields, baseline, version, entry, sourceSaved }),
      );
    else storage.removeItem(draftKey);
  }, [draftKey, fields, baseline, version, entry, sourceSaved, dirty]);
  useEffect(
    /* 原生模态框提供焦点约束和 Escape 关闭 */ () => {
      const element = dialog.current;
      element?.showModal();
      return /* 卸载时退出顶层模态状态 */ () => element?.close();
    },
    [],
  );
  useEffect(
    /* 未编辑时跟随识别完成状态，有草稿时保留原版本以检查冲突 */ () => {
      if (honor && !dirty) {
        setFields(honor.fields);
        setBaseline(honor.fields);
        setVersion(honor.version);
      }
    },
    [honor, dirty],
  );
  /** 关闭前保护尚未保存的人工核对内容 */
  function close() {
    if (
      !busy &&
      (!dirty || window.confirm("有尚未保存的荣誉信息，确定放弃修改吗？"))
    ) {
      storage.removeItem(draftKey);
      onClose();
    }
  }
  /** 显隐和自定义字段只留在本次简历表单，正文沿用荣誉库字段 */
  function changeEntry(value: SectionEntry) {
    setEntry(value);
    setFields(honorFieldsFromEntry(value));
  }
  /** 保存当前表单，服务端成功前保留用户输入 */
  async function save() {
    if (busy || recognizing || !fields.name.trim()) return;
    setBusy(true);
    setError("");
    let savedSource = sourceSaved;
    try {
      // 本地条目和单独的显示设置不写来源，保存失败后重试使用已确认的新版本
      if (!resumeEntry || (honor && contentDirty)) {
        const saved = await api<Honor>(
          honor ? `/honors/${honor.id}` : "/honors",
          honor ? "PUT" : "POST",
          { fields, version },
        );
        setFields(saved.fields);
        setBaseline(saved.fields);
        setVersion(saved.version);
        setSourceSaved(true);
        savedSource = true;
        onSaved(saved);
      }
      if (entry && onSaveEntry)
        await onSaveEntry(entryWithHonorFields(entry, fields));
      storage.removeItem(draftKey);
      onClose();
    } catch (reason) {
      setError(
        `${savedSource && resumeEntry ? "荣誉内容已同步；当前简历尚未保存，请重试。" : ""}${(reason as Error).message}`,
      );
    } finally {
      setBusy(false);
    }
  }
  const saveButton = (
    <button
      form="honor-form"
      type="submit"
      className="primary"
      disabled={busy || recognizing || !fields.name.trim()}
    >
      <Save size={16} />
      {busy ? "保存中…" : "确认并保存"}
    </button>
  );
  return (
    <dialog
      ref={dialog}
      className={`honor-dialog ${resumeEntry && !honor?.attachment ? "honor-entry-dialog" : ""}`}
      aria-labelledby="honor-editor-title"
      onCancel={
        /* 拦截默认关闭以保护未保存内容 */ (event) => {
          event.preventDefault();
          close();
        }
      }
    >
      <header className="honor-dialog-header">
        <div>
          <h2 id="honor-editor-title">
            {resumeEntry
              ? "编辑荣誉条目"
              : honor
                ? "核对荣誉信息"
                : "手动添加荣誉"}
          </h2>
        </div>
        <div className="honor-dialog-actions">
          {!resumeEntry && saveButton}
          <button
            type="button"
            className="icon-button"
            aria-label="关闭荣誉信息"
            onClick={close}
            disabled={busy}
          >
            <X size={20} />
          </button>
        </div>
      </header>
      {error && (
        <p role="alert" className="honor-dialog-error error">
          {error}
        </p>
      )}
      <div
        className={`honor-dialog-body ${honor?.attachment ? "" : "without-certificate"}`}
      >
        {honor?.attachment && (
          <section className="honor-original" aria-label="证书原件预览">
            <div className="honor-preview-toolbar">
              <span title={honor.attachment.name}>{honor.attachment.name}</span>
              <button
                onClick={
                  /* 下载经过鉴权的原始附件 */ () => {
                    void download(
                      `/honors/${honor.id}/original`,
                      honor.attachment!.name,
                    ).catch(
                      /* 下载失败在当前窗口提示 */ (reason: Error) =>
                        setError(reason.message),
                    );
                  }
                }
              >
                <Download size={15} />
                原件
              </button>
            </div>
            <HonorImage
              id={honor.id}
              page={page}
              name={honor.attachment.name}
            />
            {honor.attachment.pages > 1 && (
              <div className="honor-pagination">
                <button
                  aria-label="上一页证书"
                  disabled={page <= 1}
                  onClick={/* 切换到上一张分页图 */ () => setPage(page - 1)}
                >
                  <ChevronLeft size={16} />
                </button>
                <span>
                  {page} / {honor.attachment.pages} 页
                </span>
                <button
                  aria-label="下一页证书"
                  disabled={page >= honor.attachment.pages}
                  onClick={/* 切换到下一张分页图 */ () => setPage(page + 1)}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            )}
          </section>
        )}
        <form
          id="honor-form"
          className="honor-form"
          onSubmit={
            /* 表单通过浏览器必填校验后执行保存 */ (event) => {
              event.preventDefault();
              void save();
            }
          }
        >
          {honor?.error && <p className="honor-notice">{honor.error}</p>}
          {!resumeEntry &&
            honor?.status === "review" &&
            honor.recognition &&
            appliedRecognitionVersion !== honor.version && (
              <div className="honor-notice">
                <p>
                  {honor.reviewed
                    ? "下方保留已确认的资料，可以选择填入本次识别结果后再保存。"
                    : "识别信息已填入下方，请对照原件核对。空白字段可补充或留空。"}
                </p>
                {honor.recognition.warnings.map(
                  /* 展示模型标出的不确定信息 */ (warning, index) => (
                    <p key={index}>{warning}</p>
                  ),
                )}
                {honor.reviewed && (
                  <button
                    type="button"
                    disabled={recognizing || busy}
                    onClick={
                      /* 填入后收起本次提示，下一次新识别仍可独立核对 */ () => {
                        setFields(honor.recognition!.fields);
                        setAppliedRecognitionVersion(honor.version);
                      }
                    }
                  >
                    将本次识别结果填入表单
                  </button>
                )}
              </div>
            )}
          {recognizing && (
            <p role="status" className="honor-notice">
              正在识别，完成后会自动填入信息。也可以关闭窗口，在列表中取消识别后手动填写。
            </p>
          )}
          <fieldset disabled={busy || recognizing}>
            {entry ? (
              <>
                <div className="section-heading">
                  <h3>荣誉信息</h3>
                  <div className="row">
                    <VisibilityButton
                      label="整条荣誉"
                      hidden={entry.visible === false}
                      disabled={busy || recognizing}
                      onToggle={
                        /* 整条隐藏和各个字段的显示选择互不覆盖 */ () =>
                          setEntry({
                            ...entry,
                            visible: entry.visible === false,
                          })
                      }
                    />
                  </div>
                </div>
                <HonorEntryFields
                  entry={entryWithHonorFields(entry, fields)}
                  idPrefix="honor-edit"
                  scope="荣誉条目"
                  editing={true}
                  saving={busy || recognizing}
                  expanded={expanded}
                  onExpanded={setExpanded}
                  onChange={changeEntry}
                  onAddInfo={
                    /* 在其他荣誉信息中添加仅属于当前简历的自定义资料 */ () => {
                      setExpanded(true);
                      setEntry({
                        ...entry,
                        custom_fields: [
                          ...entry.custom_fields,
                          newCustomField(),
                        ],
                      });
                    }
                  }
                />
              </>
            ) : (
              <div className="honor-fields">
                {FIELDS.map(
                  /* 每个字段都有固定标签和明确的长度限制 */ (field) => (
                    <label
                      key={field.key}
                      className={
                        field.key === "name" || field.key === "issuer"
                          ? "honor-field-wide"
                          : ""
                      }
                    >
                      {field.label}
                      {field.key === "name" ? " *" : ""}
                      <input
                        required={field.key === "name"}
                        maxLength={field.max}
                        value={fields[field.key]}
                        placeholder={field.placeholder}
                        onChange={
                          /* 只更新当前输入字段 */ (event) =>
                            setFields({
                              ...fields,
                              [field.key]: event.target.value,
                            })
                        }
                      />
                    </label>
                  ),
                )}
                <label>
                  {CATEGORY.label}
                  <select
                    value={fields.category}
                    onChange={
                      /* 分类和原件内容分开维护 */ (event) =>
                        setFields({
                          ...fields,
                          category: event.target
                            .value as HonorFields["category"],
                        })
                    }
                  >
                    {CATEGORIES.map(
                      /* 列出荣誉分类 */ (category) => (
                        <option key={category}>{category}</option>
                      ),
                    )}
                  </select>
                </label>
                <label className="honor-field-wide">
                  {DESCRIPTION.label}
                  <textarea
                    rows={4}
                    maxLength={DESCRIPTION.max}
                    value={fields.description}
                    placeholder={DESCRIPTION.placeholder}
                    onChange={
                      /* 保留说明中的换行 */ (event) =>
                        setFields({
                          ...fields,
                          description: event.target.value,
                        })
                    }
                  />
                </label>
              </div>
            )}
          </fieldset>
          {(honor?.recognition?.text || honor?.attachment?.text) && (
            <details className="honor-extracted">
              <summary>查看识别原文</summary>
              <pre>{honor.recognition?.text || honor.attachment?.text}</pre>
            </details>
          )}
        </form>
      </div>
      {resumeEntry && (
        <footer className="honor-dialog-footer">
          <button type="button" onClick={close} disabled={busy}>
            取消
          </button>
          {saveButton}
        </footer>
      )}
    </dialog>
  );
}
