import { arrayMove } from "@dnd-kit/sortable";
import { ArrowDown, ArrowUp, Plus } from "lucide-react";
import { useState } from "react";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import { api } from "../../shared/lib/api";
import { loadLocal } from "../../shared/lib/storage";
import type {
  Meta,
  Profile,
  ProjectDetail,
  Revision,
} from "../../shared/types/index";
import HighlightEditor from "./HighlightEditor";
import type { EditorProps } from "./types";
import { useField } from "./useField";

/** 编辑经历元信息、来源和亮点，明确区分草稿、已保存版本与简历引用。 */
export default function Editor(props: EditorProps) {
  const { detail, revisionId, run } = props;
  const current = detail.revisions.find(
    /* 定位与当前标识或条件匹配的条目。 */ (r) => r.id === revisionId,
  )!;
  const snapshot = detail.revision_snapshot;
  const [roots, setRoots] = useState(detail.project.roots.join("\n"));
  const content = detail.working.content;
  const [ordering, setOrdering] = useState(false);
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
    detail.working.drafts.find(
      /* 定位与当前标识或条件匹配的条目。 */ (d) => d.field === "meta",
    )?.version ?? 0,
    props.onDirty,
  );
  const [metaOpen, setMetaOpen] = useState(!content.description);
  const [stackText, setStackText] = useState(editor.value.stack.join("、"));
  const profileKey = `rm.profile.${detail.project.id}`;
  const [profile, setProfile] = useState<Profile>(
    /* 仅在首次挂载时读取缓存或计算初始状态。 */ () =>
      loadLocal(profileKey, detail.project.profile),
  );
  /** 更新本人贡献信息并保存本机恢复副本，等待用户正式保存。 */
  function updateProfile(key: keyof Profile, value: string) {
    const next = { ...profile, [key]: value };
    setProfile(next);
    localStorage.setItem(profileKey, JSON.stringify(next));
  }
  /** 按目标位置移动条目，并沿用当前组件的版本或组合保存规则。 */
  async function move(from: number, to: number) {
    if (ordering || from === to) return;
    setOrdering(true);
    try {
      const order = arrayMove(content.highlights, from, to).map(
        /* 逐项转换数据，保留当前业务需要的字段。 */ (h) => h.id,
      );
      const fresh = await api<ProjectDetail>(
        `/projects/${detail.project.id}?revision_id=${revisionId}`,
      );
      await api(`/projects/${detail.project.id}/draft`, "PUT", {
        base_revision: revisionId,
        field: "order",
        value: order,
        version:
          fresh.working.drafts.find(
            /* 定位与当前标识或条件匹配的条目。 */ (d) => d.field === "order",
          )?.version ?? 0,
      });
      await props.onSave("order");
    } finally {
      setOrdering(false);
    }
  }
  return (
    <div className="editor">
      <div className="version-row">
        <label>
          经历版本
          <select
            value={revisionId}
            onChange={
              /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                props.onRevision(e.target.value)
            }
          >
            {detail.revisions.map(
              /* 按稳定标识生成对应的列表条目。 */ (r) => (
                <option key={r.id} value={r.id}>
                  r{r.number} ·{" "}
                  {r.origin === "ai"
                    ? "AI 建议保存"
                    : r.origin === "restore"
                      ? "历史恢复"
                      : "人工保存"}{" "}
                  · {new Date(r.created_at).toLocaleString()}
                </option>
              ),
            )}
          </select>
        </label>
        <div className="version-actions">
          <button
            className="primary"
            data-guide="experience-save"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                run(
                  /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                    props.onSave("experience"),
                )
            }
          >
            保存全部修改
          </button>
          <button
            data-guide="experience-use"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                run(
                  /* 在草稿刷新成功后执行当前业务操作。 */ async () =>
                    props.onUseVersion(),
                )
            }
          >
            用于当前简历
          </button>
        </div>
      </div>
      <div className="meta-line">
        <span>正在编辑 r{current.number}</span>
        <span
          className={
            props.usedRevision && props.usedRevision.id !== current.id
              ? "tag warning-tag"
              : "tag"
          }
        >
          {props.usedRevision
            ? `简历引用 r${props.usedRevision.number}`
            : "尚未加入当前简历"}
        </span>
        <span>
          {props.hasLocalChanges
            ? "有修改待保存到版本"
            : detail.working.drafts.length
              ? `${detail.working.drafts.length} 个字段有草稿`
              : "内容已保存"}
        </span>
        {revisionId !== detail.project.head_revision && (
          <button
            className="text-button"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                run(
                  /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
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
                  },
                )
            }
          >
            恢复为新版本
          </button>
        )}
      </div>
      {(props.hasLocalChanges || detail.working.drafts.length > 0) && (
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
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                setMetaOpen(!metaOpen)
            }
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
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
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
                  onChange={
                    /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                      editor.update({ ...editor.value, period: e.target.value })
                  }
                />
              </label>
              <label>
                担任角色
                <input
                  placeholder="由本人填写"
                  value={editor.value.role}
                  onChange={
                    /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                      editor.update({ ...editor.value, role: e.target.value })
                  }
                />
              </label>
            </div>
            <label>
              技术栈（用顿号或逗号分隔）
              <input
                value={stackText}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) => {
                    setStackText(e.target.value);
                    editor.update({
                      ...editor.value,
                      stack: e.target.value
                        .split(/[、,，]/)
                        .map(
                          /* 逐项转换数据，保留当前业务需要的字段。 */ (v) =>
                            v.trim(),
                        )
                        .filter(Boolean),
                    });
                  }
                }
              />
            </label>
            <label>
              项目描述
              <textarea
                rows={3}
                value={editor.value.description}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    editor.update({
                      ...editor.value,
                      description: e.target.value,
                    })
                }
              />
            </label>
            <div className="actions">
              <button
                onClick={
                  /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                    run(
                      /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                        await editor.flush();
                        await props.onSave("meta");
                      },
                    )
                }
              >
                保存基本信息
              </button>
              <span className="subtle">{editor.status}</span>
              {editor.conflict && (
                <button
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      void editor.reloadRemote().then(
                        /* 在异步操作成功后同步结果及相关状态。 */ (value) => {
                          if (value) setStackText(value.stack.join("、"));
                        },
                      )
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
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                  const id = crypto.randomUUID();
                  await api(`/projects/${detail.project.id}/draft`, "PUT", {
                    base_revision: revisionId,
                    field: `highlight:${id}`,
                    value: { id, title: "", text: "", evidence: [] },
                    version: 0,
                  });
                  props.onRefresh();
                },
              )
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
      <SortableList
        items={content.highlights.map(
          /* 逐项转换数据，保留当前业务需要的字段。 */ (item) => ({
            id: item.id,
            label: item.title || "未命名亮点",
          }),
        )}
        disabled={ordering}
        onMove={
          /* 将排序落点交给当前业务的移动操作。 */ (from, to) =>
            run(/* 在草稿刷新成功后执行当前业务操作。 */ () => move(from, to))
        }
      >
        {content.highlights.map(
          /* 按稳定标识生成对应的列表条目。 */ (item, index) => (
            <SortableItem
              key={`${item.id}.${detail.working.drafts.find(/* 定位与当前标识或条件匹配的条目。 */ (d) => d.field === `highlight:${item.id}`)?.version ?? 0}`}
              id={item.id}
              label={`亮点 ${item.title || "未命名亮点"}`}
              className="point-row"
            >
              {
                /* 将排序手柄嵌入对应业务条目的操作区。 */ (handle) => (
                  <>
                    <HighlightEditor
                      item={item}
                      draftVersion={
                        detail.working.drafts.find(
                          /* 定位与当前标识或条件匹配的条目。 */ (d) =>
                            d.field === `highlight:${item.id}`,
                        )?.version ?? 0
                      }
                      props={props}
                    />
                    <div className="point-order">
                      <button
                        className="icon-button"
                        aria-label={`上移 ${item.title}`}
                        disabled={ordering || index === 0}
                        onClick={
                          /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                            run(
                              /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                                move(index, index - 1),
                            )
                        }
                      >
                        <ArrowUp size={13} />
                      </button>
                      {handle}
                      <button
                        className="icon-button"
                        aria-label={`下移 ${item.title}`}
                        disabled={
                          ordering || index === content.highlights.length - 1
                        }
                        onClick={
                          /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                            run(
                              /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                                move(index, index + 1),
                            )
                        }
                      >
                        <ArrowDown size={13} />
                      </button>
                    </div>
                  </>
                )
              }
            </SortableItem>
          ),
        )}
      </SortableList>
      <details className="source-details">
        <summary>项目来源与本人贡献</summary>
        {snapshot ? (
          <div className="snapshot-info">
            <b>r{current.number} 的来源版本</b>
            <code className="path">{snapshot.fingerprint}</code>
            {snapshot.manifest.sources.map(
              /* 按稳定标识生成对应的列表条目。 */ (source) => (
                <div key={source.id}>
                  <b>{source.name}</b>
                  <code>{source.path}</code>
                  <code>
                    {source.commit || "普通目录"} {source.branch}{" "}
                    {source.dirty ? "· 含未提交修改" : ""}
                  </code>
                </div>
              ),
            )}
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
        {detail.project.roots.map(
          /* 按稳定标识生成对应的列表条目。 */ (root) => (
            <code className="path" key={root}>
              {root}
            </code>
          ),
        )}
        <details>
          <summary>重新绑定项目目录</summary>
          <label>
            来源路径（每行一个）
            <textarea
              rows={3}
              value={roots}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                  setRoots(e.target.value)
              }
            />
          </label>
          <button
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                run(
                  /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                    await api(`/projects/${detail.project.id}/sources`, "PUT", {
                      name: detail.project.name,
                      roots: roots
                        .split("\n")
                        .map(
                          /* 逐项转换数据，保留当前业务需要的字段。 */ (v) =>
                            v.trim(),
                        )
                        .filter(Boolean),
                    });
                    props.onRefresh();
                  },
                )
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
            {detail.snapshots[0].manifest.sources.map(
              /* 按稳定标识生成对应的列表条目。 */ (s) => (
                <div key={s.id}>
                  <b>{s.name}</b>
                  <code>
                    {s.commit || "普通目录"} {s.dirty ? "· 含未提交修改" : ""}
                  </code>
                </div>
              ),
            )}
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
        ).map(
          /* 按稳定标识生成对应的列表条目。 */ ([key, label]) => (
            <label key={key}>
              {label}
              <textarea
                rows={key === "contribution" || key === "outcomes" ? 3 : 2}
                value={profile[key]}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    updateProfile(key, e.target.value)
                }
              />
            </label>
          ),
        )}
        <button
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                  await api(
                    `/projects/${detail.project.id}/profile`,
                    "PUT",
                    profile,
                  );
                  localStorage.removeItem(profileKey);
                  props.onRefresh();
                },
              )
          }
        >
          保存本人贡献资料
        </button>
      </details>
    </div>
  );
}
