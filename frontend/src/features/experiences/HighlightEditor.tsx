import { Check, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../../shared/lib/api";
import type { Highlight, ProjectDetail } from "../../shared/types";
import type { EditorProps } from "./types";
import { useField } from "./useField";
/** 编辑单条亮点及证据，支持单项保存、丢弃、删除和 AI 修改。 */
export default function HighlightEditor({
  item,
  draftVersion,
  props,
}: {
  item: Highlight;
  draftVersion: number;
  props: EditorProps;
}) {
  const { detail, revisionId, run } = props;
  const field = `highlight:${item.id}`;
  const editor = useField(
    detail.project.id,
    revisionId,
    field,
    item,
    draftVersion,
    props.onDirty,
  );
  const [editing, setEditing] = useState(!item.title || !item.text);
  const { value } = editor;
  return (
    <article className="highlight" data-highlight-id={item.id}>
      <div className="highlight-heading">
        <input
          type="checkbox"
          aria-label={`选中亮点 ${value.title || "新亮点"}`}
          checked={props.included.includes(item.id)}
          onChange={
            /* 把控件的新值同步到对应编辑状态。 */ () => props.onToggle(item.id)
          }
        />
        <div className="grow">
          <strong>{value.title || "新亮点"}</strong>
          {!editing && <p>{value.text || "填写这条经历的具体内容。"}</p>}
        </div>
        <button
          className="text-button"
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
              setEditing(!editing)
          }
        >
          {editing ? "收起" : "编辑"}
        </button>
      </div>
      {editing && (
        <div className="highlight-form">
          <label>
            亮点标题
            <input
              value={value.title}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                  editor.update({ ...value, title: e.target.value })
              }
            />
          </label>
          <label>
            亮点正文
            <textarea
              rows={4}
              value={value.text}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                  editor.update({
                    ...value,
                    text: e.target.value,
                    evidence: value.evidence.map(
                      /* 逐项转换数据，保留当前业务需要的字段。 */ (v) => ({
                        ...v,
                        status: "unverified",
                      }),
                    ),
                  })
              }
            />
          </label>
          <div className="actions">
            <button
              className="primary"
              disabled={!value.title.trim() || !value.text.trim()}
              onClick={
                /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                      await editor.flush();
                      await props.onSave(field);
                    },
                  )
              }
            >
              <Check size={15} />
              保存此条
            </button>
            <button
              onClick={
                /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
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
                    },
                  )
              }
            >
              取消编辑
            </button>
            <span className="subtle save-status" aria-live="polite">
              {editor.status}
            </span>
            {editor.conflict && (
              <button
                onClick={
                  /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                    void editor.reloadRemote()
                }
              >
                载入服务器草稿
              </button>
            )}
          </div>
        </div>
      )}
      <div className="highlight-tools">
        <button
          className="text-button"
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                  props.onAsk(field),
              )
          }
        >
          <Sparkles size={14} />让 AI 修改
        </button>
        <button
          className="icon-button danger-hover"
          aria-label={`删除亮点 ${value.title}`}
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                  await editor.flush();
                  const fresh = await api<ProjectDetail>(
                    `/projects/${detail.project.id}?revision_id=${revisionId}`,
                  );
                  const version =
                    fresh.working.drafts.find(
                      /* 定位与当前标识或条件匹配的条目。 */ (d) =>
                        d.field === field,
                    )?.version ?? 0;
                  await api(`/projects/${detail.project.id}/draft`, "PUT", {
                    base_revision: revisionId,
                    field,
                    value: null,
                    version,
                  });
                  await props.onSave(field);
                },
              )
          }
        >
          <Trash2 size={14} />
        </button>
      </div>
      {value.evidence.length > 0 && (
        <details className="evidence">
          <summary>
            来源证据 ·{" "}
            {
              value.evidence.filter(
                /* 保留满足当前范围或有效性条件的条目。 */ (v) =>
                  v.status === "code" || v.status === "document",
              ).length
            }{" "}
            条引用已校验
          </summary>
          {value.evidence.map(
            /* 按稳定标识生成对应的列表条目。 */ (e, index) => (
              <div className="evidence-entry" key={index}>
                <span className="tag">
                  {e.status === "unverified"
                    ? "待确认"
                    : e.status === "user"
                      ? "本人确认"
                      : "原文匹配"}
                </span>
                <code>
                  {e.source}/{e.path}:{e.line_start}–{e.line_end}
                </code>
                <pre>{e.quote}</pre>
              </div>
            ),
          )}
        </details>
      )}
    </article>
  );
}
