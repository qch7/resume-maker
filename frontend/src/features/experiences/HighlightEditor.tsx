import { Check, FileText, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../shared/lib/api";
import type { Highlight, ProjectDetail } from "../../shared/types";
import type { EditorProps } from "./types";
import { useField } from "./useField";
import EvidenceDialog from "./EvidenceDialog";
import { editHighlightText, fieldChanged } from "./changes";
import { VisibilityButton } from "../profile/VisibilityField";
/** 编辑亮点和证据并将增删改暂存为草稿 */
export default function HighlightEditor({
  item,
  draftVersion,
  props,
  onPreview,
}: {
  item: Highlight;
  draftVersion: number;
  props: EditorProps;
  onPreview: (value: Highlight) => void;
}) {
  const { detail, revisionId, run } = props;
  const field = `highlight:${item.id}`;
  const base = detail.revisions.find(
    /* 读取当前不可变基线 */ (revision) => revision.id === revisionId,
  )!.content;
  const editor = useField(
    detail.project.id,
    revisionId,
    field,
    item,
    draftVersion,
    /* 亮点正文改回原文后不再显示待提交 */ (value) =>
      fieldChanged(value, base, field),
  );
  const [editing, setEditing] = useState(!item.title || !item.text);
  const [showEvidence, setShowEvidence] = useState(false);
  const { value } = editor;
  useEffect(
    /* 输入和本机草稿恢复立即进入实时预览，无需等待网络防抖保存 */ () =>
      onPreview(value),
    [value, onPreview],
  );
  return (
    <article
      className="highlight"
      data-highlight-id={item.id}
      data-hidden={!props.included.includes(item.id) || undefined}
    >
      <div className="highlight-heading">
        <strong className="grow">{value.title || "新亮点"}</strong>
        <div className="highlight-tools">
          <VisibilityButton
            label={`亮点 ${value.title || "新亮点"}`}
            hidden={!props.included.includes(item.id)}
            onToggle={
              /* 仅切换当前简历中的亮点显示，原文及项目版本不变 */ () =>
                props.onToggle(item.id)
            }
          />
          <button
            className="text-button"
            title="让 AI 修改"
            aria-label={`让 AI 修改亮点 ${value.title}`}
            onClick={
              /* 切换到当前亮点的 AI 讨论范围 */ () =>
                run(/* 刷新草稿后进入会话 */ () => props.onAsk(field))
            }
          >
            <Sparkles size={14} />
            <span className="highlight-tool-label">让 AI 修改</span>
          </button>
          <button
            className="text-button"
            title={`来源引用（${value.evidence.length} 条）`}
            aria-label={`来源引用（${value.evidence.length} 条）`}
            aria-haspopup="dialog"
            onClick={/* 展示当前亮点的来源引用 */ () => setShowEvidence(true)}
          >
            <FileText size={14} />
            <span className="highlight-tool-label">来源引用</span>
            <span className="highlight-evidence-count">
              {value.evidence.length}
            </span>
          </button>
          <button className="text-button" onClick={() => setEditing(!editing)}>
            {editing ? "收起" : "编辑"}
          </button>
          <button
            className="icon-button danger-hover"
            title="删除亮点"
            aria-label={`删除亮点 ${value.title}`}
            onClick={
              /* 保存删除操作前刷新草稿并读取最新版本以免覆盖并发编辑 */ () =>
                run(
                  /* 删除结果暂存于工作副本 */ async () => {
                    await editor.flush();
                    const fresh = await api<ProjectDetail>(
                      `/projects/${detail.project.id}?revision_id=${revisionId}`,
                    );
                    const version =
                      fresh.working.drafts.find(
                        /* 查找当前亮点的草稿版本 */ (d) => d.field === field,
                      )?.version ?? 0;
                    await api(`/projects/${detail.project.id}/draft`, "PUT", {
                      base_revision: revisionId,
                      field,
                      value: null,
                      version,
                    });
                    props.onRefresh();
                  },
                )
            }
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {!editing && (
        <p className="highlight-text">
          {value.text || "填写这条经历的具体内容。"}
        </p>
      )}
      {editing && (
        <div className="highlight-form">
          <label>
            亮点标题
            <input
              value={value.title}
              onChange={(e) =>
                editor.update({ ...value, title: e.target.value })
              }
            />
          </label>
          <label>
            亮点正文
            <textarea
              rows={4}
              value={value.text}
              onChange={(e) =>
                editor.update(
                  editHighlightText(
                    value,
                    e.target.value,
                    base.highlights.find(
                      /* 同时恢复原文对应的证据核实状态 */ (point) =>
                        point.id === item.id,
                    ),
                  ),
                )
              }
            />
          </label>
          <div className="actions">
            <button
              className="primary"
              disabled={!value.title.trim() || !value.text.trim()}
              onClick={() =>
                run(async () => {
                  await editor.flush();
                  setEditing(false);
                  props.onRefresh();
                })
              }
            >
              <Check size={15} />
              完成编辑
            </button>
            <button
              onClick={() =>
                run(async () => {
                  await editor.flush();
                  await api(
                    `/projects/${detail.project.id}/draft/discard`,
                    "POST",
                    {
                      base_revision: revisionId,
                      field,
                      version: editor.version.current,
                    },
                  );
                  localStorage.removeItem(
                    `rm.field.${detail.project.id}.${revisionId}.${field}`,
                  );
                  props.onRefresh();
                })
              }
            >
              取消编辑
            </button>
            <span className="subtle save-status" aria-live="polite">
              {editor.status}
            </span>
            {editor.conflict && (
              <button onClick={() => void editor.reloadRemote()}>
                载入服务器草稿
              </button>
            )}
          </div>
        </div>
      )}
      {showEvidence && (
        <EvidenceDialog
          title={value.title || "新亮点"}
          evidence={value.evidence}
          detail={detail}
          onClose={
            /* 关闭弹窗并恢复触发按钮焦点 */ () => setShowEvidence(false)
          }
        />
      )}
    </article>
  );
}
