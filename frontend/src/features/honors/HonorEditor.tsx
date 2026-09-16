import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Save, X } from "lucide-react";
import { api, download } from "../../shared/lib/api";
import HonorImage from "./HonorImage";
import {
  CATEGORIES,
  emptyHonor,
  isRecognizing,
  STATUS,
  type Honor,
  type HonorFields,
} from "./model";

const FIELDS: {
  key: Exclude<keyof HonorFields, "category" | "description">;
  label: string;
  placeholder: string;
  max: number;
}[] = [
  {
    key: "name",
    label: "荣誉 / 证书名称",
    placeholder: "例如：全国大学生数学建模竞赛",
    max: 300,
  },
  {
    key: "award",
    label: "奖项 / 等次",
    placeholder: "例如：一等奖、金奖",
    max: 200,
  },
  {
    key: "level",
    label: "荣誉级别",
    placeholder: "例如：国家级、省级、校级",
    max: 100,
  },
  {
    key: "issuer",
    label: "颁发单位",
    placeholder: "证书上标注的主办或认证机构",
    max: 500,
  },
  {
    key: "date",
    label: "获得日期",
    placeholder: "例如：2026-06 或 2026",
    max: 100,
  },
  {
    key: "recipient",
    label: "获奖人 / 团队",
    placeholder: "证书上标注的姓名或团队",
    max: 300,
  },
  {
    key: "certificate_number",
    label: "证书编号",
    placeholder: "没有编号可留空",
    max: 300,
  },
];

/** 对照原件核对识别结果；保留未保存表单，并用版本号防止并发覆盖。 */
export default function HonorEditor({
  honor,
  onClose,
  onSaved,
}: {
  honor: Honor | null;
  onClose: () => void;
  onSaved: (honor: Honor) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [fields, setFields] = useState(honor?.fields ?? emptyHonor());
  const [baseline, setBaseline] = useState(honor?.fields ?? emptyHonor());
  const [version, setVersion] = useState(honor?.version ?? 0);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dirty = JSON.stringify(fields) !== JSON.stringify(baseline);
  const recognizing = honor ? isRecognizing(honor) : false;
  useEffect(
    /* 原生模态框提供焦点约束和 Escape 关闭。 */ () => {
      const element = dialog.current;
      element?.showModal();
      return /* 卸载时退出顶层模态状态。 */ () => element?.close();
    },
    [],
  );
  useEffect(
    /* 未编辑时跟随识别完成状态，有草稿时保留原版本以检查冲突。 */ () => {
      if (honor && !dirty) {
        setFields(honor.fields);
        setBaseline(honor.fields);
        setVersion(honor.version);
      }
    },
    [honor, dirty],
  );
  /** 关闭前保护尚未保存的人工核对内容。 */
  function close() {
    if (
      !busy &&
      (!dirty || window.confirm("有尚未保存的荣誉信息，确定放弃修改吗？"))
    )
      onClose();
  }
  /** 保存当前表单，服务端成功前保留用户输入。 */
  async function save() {
    if (busy || recognizing) return;
    setBusy(true);
    setError("");
    try {
      const saved = await api<Honor>(
        honor ? `/honors/${honor.id}` : "/honors",
        honor ? "PUT" : "POST",
        { fields, version },
      );
      onSaved(saved);
      onClose();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="honor-dialog"
      aria-labelledby="honor-editor-title"
      onCancel={
        /* 拦截默认关闭以保护未保存内容。 */ (event) => {
          event.preventDefault();
          close();
        }
      }
    >
      <header className="honor-dialog-header">
        <div>
          <h2 id="honor-editor-title">
            {honor ? "核对荣誉信息" : "手动添加荣誉"}
          </h2>
          <p className="subtle">
            {honor
              ? `${STATUS[honor.status]} · 信息以证书原件为准`
              : "没有电子证书，也可以先整理荣誉资料。"}
          </p>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="关闭荣誉信息"
          onClick={close}
          disabled={busy}
        >
          <X size={20} />
        </button>
      </header>
      <div
        className={`honor-dialog-body ${honor?.attachment ? "" : "without-certificate"}`}
      >
        {honor?.attachment && (
          <section className="honor-original" aria-label="证书原件预览">
            <div className="honor-preview-toolbar">
              <span title={honor.attachment.name}>{honor.attachment.name}</span>
              <button
                onClick={
                  /* 下载经过鉴权的原始附件。 */ () => {
                    void download(
                      `/honors/${honor.id}/original`,
                      honor.attachment!.name,
                    ).catch(
                      /* 下载失败在当前窗口提示。 */ (reason: Error) =>
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
                  onClick={/* 切换到上一张分页图。 */ () => setPage(page - 1)}
                >
                  <ChevronLeft size={16} />
                </button>
                <span>
                  {page} / {honor.attachment.pages} 页
                </span>
                <button
                  aria-label="下一页证书"
                  disabled={page >= honor.attachment.pages}
                  onClick={/* 切换到下一张分页图。 */ () => setPage(page + 1)}
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
            /* 表单通过浏览器必填校验后执行保存。 */ (event) => {
              event.preventDefault();
              void save();
            }
          }
        >
          {honor?.error && <p className="honor-notice">{honor.error}</p>}
          {honor?.recognition && (
            <div className="honor-notice">
              <p>
                {honor.reviewed
                  ? "下方保留已确认的资料，可以选择填入本次识别结果后再保存。"
                  : "识别信息已填入下方，请对照原件核对。空白字段可补充或留空。"}
              </p>
              {honor.recognition.warnings.map(
                /* 展示模型标出的不确定信息。 */ (warning, index) => (
                  <p key={index}>{warning}</p>
                ),
              )}
              {honor.reviewed && (
                <button
                  type="button"
                  disabled={recognizing || busy}
                  onClick={
                    /* 重识别结果先进入表单，保存后才替换人工版本。 */ () =>
                      setFields(honor.recognition!.fields)
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
            <div className="honor-fields">
              {FIELDS.map(
                /* 每个字段都有固定标签和明确的长度限制。 */ (field) => (
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
                        /* 只更新当前输入字段。 */ (event) =>
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
                分类
                <select
                  value={fields.category}
                  onChange={
                    /* 分类与原件内容分开维护。 */ (event) =>
                      setFields({
                        ...fields,
                        category: event.target.value as HonorFields["category"],
                      })
                  }
                >
                  {CATEGORIES.map(
                    /* 列出统一的荣誉分类。 */ (category) => (
                      <option key={category}>{category}</option>
                    ),
                  )}
                </select>
              </label>
              <label className="honor-field-wide">
                说明 / 获奖项目
                <textarea
                  rows={4}
                  maxLength={5000}
                  value={fields.description}
                  placeholder="补充获奖项目、证书用途或其他备注"
                  onChange={
                    /* 保留说明中的换行。 */ (event) =>
                      setFields({ ...fields, description: event.target.value })
                  }
                />
              </label>
            </div>
          </fieldset>
          {(honor?.recognition?.text || honor?.attachment?.text) && (
            <details className="honor-extracted">
              <summary>查看识别原文</summary>
              <pre>{honor.recognition?.text || honor.attachment?.text}</pre>
            </details>
          )}
        </form>
      </div>
      <footer className="honor-dialog-footer">
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <span className="subtle">保存至荣誉库，可在不同简历中重复使用。</span>
        <button type="button" onClick={close} disabled={busy}>
          关闭
        </button>
        <button
          form="honor-form"
          type="submit"
          className="primary"
          disabled={busy || recognizing || !fields.name.trim()}
        >
          <Save size={16} />
          {busy ? "保存中…" : "确认并保存"}
        </button>
      </footer>
    </dialog>
  );
}
