import { useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { api, loadLocal } from "./api";
import { useField } from "./drafts";
import type {
  Highlight,
  Meta,
  Profile,
  ProjectDetail,
  Revision,
} from "./types";

interface Props {
  detail: ProjectDetail;
  revisionId: string;
  included: string[];
  run: (work: () => Promise<void>) => void;
  onSave: (field: string) => Promise<void>;
  onRefresh: () => void;
  onRevision: (id: string) => void;
  onUseVersion: () => void;
  onAsk: (scope: string) => Promise<void>;
  onToggle: (id: string) => void;
}

function HighlightEditor({
  item,
  draftVersion,
  props,
}: {
  item: Highlight;
  draftVersion: number;
  props: Props;
}) {
  const { detail, revisionId, run } = props;
  const field = `highlight:${item.id}`;
  const editor = useField(
    detail.project.id,
    revisionId,
    field,
    item,
    draftVersion,
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
          onChange={() => props.onToggle(item.id)}
        />
        <div className="grow">
          <strong>{value.title || "新亮点"}</strong>
          {!editing && <p>{value.text || "填写这条经历的具体内容。"}</p>}
        </div>
        <button className="text-button" onClick={() => setEditing(!editing)}>
          {editing ? "收起" : "编辑"}
        </button>
      </div>
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
                editor.update({
                  ...value,
                  text: e.target.value,
                  evidence: value.evidence.map((v) => ({
                    ...v,
                    status: "unverified",
                  })),
                })
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
                  await props.onSave(field);
                })
              }
            >
              <Check size={15} />
              保存此条
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
      <div className="highlight-tools">
        <button
          className="text-button"
          onClick={() => run(() => props.onAsk(field))}
        >
          <Sparkles size={14} />让 AI 修改
        </button>
        <button
          className="icon-button danger-hover"
          aria-label={`删除亮点 ${value.title}`}
          onClick={() =>
            run(async () => {
              await editor.flush();
              const fresh = await api<ProjectDetail>(
                `/projects/${detail.project.id}?revision_id=${revisionId}`,
              );
              const version =
                fresh.working.drafts.find((d) => d.field === field)?.version ??
                0;
              await api(`/projects/${detail.project.id}/draft`, "PUT", {
                base_revision: revisionId,
                field,
                value: null,
                version,
              });
              await props.onSave(field);
            })
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
                (v) => v.status === "code" || v.status === "document",
              ).length
            }{" "}
            条引用已校验
          </summary>
          {value.evidence.map((e, index) => (
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
          ))}
        </details>
      )}
    </article>
  );
}

export default function Editor(props: Props) {
  const { detail, revisionId, run } = props;
  const current = detail.revisions.find((r) => r.id === revisionId)!;
  const snapshot = detail.revision_snapshot;
  const [roots, setRoots] = useState(detail.project.roots.join("\n"));
  const content = detail.working.content;
  const meta: Meta = {
    title: content.title,
    period: content.period,
    role: content.role,
    stack: content.stack,
    description: content.description,
  };
  const editor = useField(
    detail.project.id,
    revisionId,
    "meta",
    meta,
    detail.working.drafts.find((d) => d.field === "meta")?.version ?? 0,
  );
  const [metaOpen, setMetaOpen] = useState(!content.description);
  const [stackText, setStackText] = useState(editor.value.stack.join("、"));
  const profileKey = `rm.profile.${detail.project.id}`;
  const [profile, setProfile] = useState<Profile>(() =>
    loadLocal(profileKey, detail.project.profile),
  );
  function updateProfile(key: keyof Profile, value: string) {
    const next = { ...profile, [key]: value };
    setProfile(next);
    localStorage.setItem(profileKey, JSON.stringify(next));
  }
  async function move(index: number, delta: number) {
    const order = content.highlights.map((h) => h.id);
    [order[index], order[index + delta]] = [order[index + delta], order[index]];
    const fresh = await api<ProjectDetail>(
      `/projects/${detail.project.id}?revision_id=${revisionId}`,
    );
    await api(`/projects/${detail.project.id}/draft`, "PUT", {
      base_revision: revisionId,
      field: "order",
      value: order,
      version:
        fresh.working.drafts.find((d) => d.field === "order")?.version ?? 0,
    });
    await props.onSave("order");
  }
  return (
    <div className="editor">
      <div className="version-row">
        <label>
          经历版本
          <select
            value={revisionId}
            onChange={(e) => props.onRevision(e.target.value)}
          >
            {detail.revisions.map((r) => (
              <option key={r.id} value={r.id}>
                r{r.number} ·{" "}
                {r.origin === "ai"
                  ? "AI 建议保存"
                  : r.origin === "restore"
                    ? "历史恢复"
                    : "人工保存"}{" "}
                · {new Date(r.created_at).toLocaleString()}
              </option>
            ))}
          </select>
        </label>
        <div className="version-actions">
          <button
            className="primary"
            onClick={() => run(() => props.onSave("experience"))}
          >
            保存全部修改
          </button>
          <button onClick={props.onUseVersion}>用于当前简历</button>
        </div>
      </div>
      <div className="meta-line">
        <span>正在编辑 r{current.number}</span>
        <span>
          {detail.working.drafts.length
            ? `${detail.working.drafts.length} 个字段有草稿`
            : "内容已保存"}
        </span>
        {revisionId !== detail.project.head_revision && (
          <button
            className="text-button"
            onClick={() =>
              run(async () => {
                const restored = await api<Revision>(
                  `/projects/${detail.project.id}/restore`,
                  "POST",
                  {
                    base_revision: revisionId,
                    field: "experience",
                    expected_head: detail.project.head_revision,
                  },
                );
                props.onRevision(restored.id);
                props.onRefresh();
              })
            }
          >
            恢复为新版本
          </button>
        )}
      </div>
      {detail.working.drafts.length > 0 && (
        <div className="notice">
          <span>
            草稿尚未保存到经历版本。可逐条保存，或点击“保存全部修改”一起保存。
          </span>
        </div>
      )}
      <section className="project-meta">
        <div className="section-heading">
          <h2>{editor.value.title}</h2>
          <button
            className="text-button"
            onClick={() => setMetaOpen(!metaOpen)}
          >
            {metaOpen ? "收起信息" : "编辑基本信息"}
          </button>
        </div>
        {metaOpen ? (
          <>
            <label>
              项目标题
              <input
                value={editor.value.title}
                onChange={(e) =>
                  editor.update({ ...editor.value, title: e.target.value })
                }
              />
            </label>
            <div className="form-grid">
              <label>
                参与时间
                <input
                  placeholder="例如 2026.2 - 2026.4"
                  value={editor.value.period}
                  onChange={(e) =>
                    editor.update({ ...editor.value, period: e.target.value })
                  }
                />
              </label>
              <label>
                担任角色
                <input
                  placeholder="由本人填写"
                  value={editor.value.role}
                  onChange={(e) =>
                    editor.update({ ...editor.value, role: e.target.value })
                  }
                />
              </label>
            </div>
            <label>
              技术栈（用顿号或逗号分隔）
              <input
                value={stackText}
                onChange={(e) => {
                  setStackText(e.target.value);
                  editor.update({
                    ...editor.value,
                    stack: e.target.value
                      .split(/[、,，]/)
                      .map((v) => v.trim())
                      .filter(Boolean),
                  });
                }}
              />
            </label>
            <label>
              项目描述
              <textarea
                rows={3}
                value={editor.value.description}
                onChange={(e) =>
                  editor.update({
                    ...editor.value,
                    description: e.target.value,
                  })
                }
              />
            </label>
            <div className="actions">
              <button
                onClick={() =>
                  run(async () => {
                    await editor.flush();
                    await props.onSave("meta");
                  })
                }
              >
                保存基本信息
              </button>
              <span className="subtle">{editor.status}</span>
              {editor.conflict && (
                <button
                  onClick={() =>
                    void editor.reloadRemote().then((value) => {
                      if (value) setStackText(value.stack.join("、"));
                    })
                  }
                >
                  载入服务器草稿
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <p className="subtle">
              {editor.value.period} {editor.value.role}
            </p>
            <p>{editor.value.stack.join(" · ")}</p>
            <p>{editor.value.description || "先分析项目，或手工补充描述。"}</p>
          </>
        )}
      </section>
      <div className="section-heading">
        <h3>项目亮点</h3>
        <button
          className="text-button"
          onClick={() =>
            run(async () => {
              const id = crypto.randomUUID();
              await api(`/projects/${detail.project.id}/draft`, "PUT", {
                base_revision: revisionId,
                field: `highlight:${id}`,
                value: { id, title: "", text: "", evidence: [] },
                version: 0,
              });
              props.onRefresh();
            })
          }
        >
          <Plus size={15} />
          新增亮点
        </button>
      </div>
      {!content.highlights.length && (
        <div className="empty compact">
          <p>还没有项目亮点</p>
          <span>可以让 Codex 分析源码，也可以直接新增并编辑。</span>
        </div>
      )}
      {content.highlights.map((item, index) => (
        <div
          key={`${item.id}.${detail.working.drafts.find((d) => d.field === `highlight:${item.id}`)?.version ?? 0}`}
          className="point-row"
        >
          <HighlightEditor
            item={item}
            draftVersion={
              detail.working.drafts.find(
                (d) => d.field === `highlight:${item.id}`,
              )?.version ?? 0
            }
            props={props}
          />
          <div className="point-order">
            <button
              className="icon-button"
              aria-label={`上移 ${item.title}`}
              disabled={index === 0}
              onClick={() => run(() => move(index, -1))}
            >
              <ArrowUp size={13} />
            </button>
            <button
              className="icon-button"
              aria-label={`下移 ${item.title}`}
              disabled={index === content.highlights.length - 1}
              onClick={() => run(() => move(index, 1))}
            >
              <ArrowDown size={13} />
            </button>
          </div>
        </div>
      ))}
      <details className="source-details">
        <summary>项目来源与本人贡献</summary>
        {snapshot ? (
          <div className="snapshot-info">
            <b>r{current.number} 的来源版本</b>
            <code className="path">{snapshot.fingerprint}</code>
            {snapshot.manifest.sources.map((source) => (
              <div key={source.id}>
                <b>{source.name}</b>
                <code>{source.path}</code>
                <code>
                  {source.commit || "普通目录"} {source.branch}{" "}
                  {source.dirty ? "· 含未提交修改" : ""}
                </code>
              </div>
            ))}
          </div>
        ) : (
          <p className="subtle">该版本尚未关联 AI 分析快照。</p>
        )}
        {snapshot &&
          detail.snapshots[0] &&
          snapshot.id !== detail.snapshots[0].id && (
            <p className="warning">
              已有更新的采集记录，当前经历仍引用原快照。
            </p>
          )}
        {detail.project.roots.map((root) => (
          <code className="path" key={root}>
            {root}
          </code>
        ))}
        <details>
          <summary>重新绑定项目目录</summary>
          <label>
            来源路径（每行一个）
            <textarea
              rows={3}
              value={roots}
              onChange={(e) => setRoots(e.target.value)}
            />
          </label>
          <button
            onClick={() =>
              run(async () => {
                await api(`/projects/${detail.project.id}/sources`, "PUT", {
                  name: detail.project.name,
                  roots: roots
                    .split("\n")
                    .map((v) => v.trim())
                    .filter(Boolean),
                });
                props.onRefresh();
              })
            }
          >
            保存来源路径
          </button>
        </details>
        {detail.snapshots[0] && (
          <div className="snapshot-info">
            <span className="subtle">
              最近采集{" "}
              {new Date(detail.snapshots[0].created_at).toLocaleString()} ·{" "}
              {detail.snapshots[0].manifest.files.length} 个文件
            </span>
            {detail.snapshots[0].manifest.sources.map((s) => (
              <div key={s.id}>
                <b>{s.name}</b>
                <code>
                  {s.commit || "普通目录"} {s.dirty ? "· 含未提交修改" : ""}
                </code>
              </div>
            ))}
            {detail.snapshots[0].manifest.omitted.length > 0 && (
              <p className="warning">
                {detail.snapshots[0].manifest.omitted.length}{" "}
                个文件因大小、编码或读取限制未纳入，可在快照记录中检查。
              </p>
            )}
          </div>
        )}
        <p className="subtle">这些信息会随下一轮对话提供给 AI。</p>
        {(
          [
            ["role", "本人角色"],
            ["period", "参与日期"],
            ["contribution", "本人负责的模块"],
            ["outcomes", "成果与量化依据"],
            ["notes", "补充说明"],
          ] as const
        ).map(([key, label]) => (
          <label key={key}>
            {label}
            <textarea
              rows={key === "contribution" || key === "outcomes" ? 3 : 2}
              value={profile[key]}
              onChange={(e) => updateProfile(key, e.target.value)}
            />
          </label>
        ))}
        <button
          onClick={() =>
            run(async () => {
              await api(
                `/projects/${detail.project.id}/profile`,
                "PUT",
                profile,
              );
              localStorage.removeItem(profileKey);
              props.onRefresh();
            })
          }
        >
          保存本人贡献资料
        </button>
      </details>
    </div>
  );
}
