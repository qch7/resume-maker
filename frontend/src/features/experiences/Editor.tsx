import PathInput from "../../shared/components/PathInput";
import { arrayMove } from "@dnd-kit/sortable";
import {
  ArrowDown,
  ArrowUp,
  BriefcaseBusiness,
  CalendarDays,
  CircleCheck,
  CircleDashed,
  Plus,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import { api } from "../../shared/lib/api";
import { loadLocal } from "../../shared/lib/storage";
import type {
  Highlight,
  Meta,
  Profile,
  Revision,
} from "../../shared/types/index";
import HighlightEditor from "./HighlightEditor";
import VersionControl from "./VersionControl";
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
  const order = useField(
    detail.project.id,
    revisionId,
    "order",
    content.highlights.map(
      /* 读取当前工作副本的亮点顺序。 */ (point) => point.id,
    ),
    detail.working.drafts.find(
      /* 沿用排序草稿的并发版本。 */ (draft) => draft.field === "order",
    )?.version ?? 0,
    props.onDirty,
  );
  const [highlightValues, setHighlightValues] = useState<
    Record<string, Highlight>
  >({});
  /** 收集亮点实时输入，供父级组合预览使用。 */
  const updateHighlightPreview = useCallback(
    /* 收集各亮点当前输入值，使用稳定回调避免预览反馈循环。 */ (
      point: Highlight,
    ) => {
      setHighlightValues(
        /* 值未变化时复用状态。 */ (values) =>
          values[point.id] === point
            ? values
            : { ...values, [point.id]: point },
      );
    },
    [],
  );
  const orderedHighlights = useMemo(
    /* 恢复本机尚未写入服务器的排序，新亮点仍置于顶部。 */ () =>
      [...content.highlights].sort(
        /* 按工作副本顺序显示卡片。 */ (a, b) =>
          order.value.indexOf(a.id) - order.value.indexOf(b.id),
      ),
    [content.highlights, order.value],
  );
  const previewContent = useMemo(
    /* 合并元信息、亮点输入与排序，右侧始终使用编辑区的当前值。 */ () => ({
      ...editor.value,
      highlights: orderedHighlights.map(
        /* 尚未挂载的条目使用已恢复的工作副本。 */ (point) =>
          highlightValues[point.id] ?? point,
      ),
    }),
    [editor.value, orderedHighlights, highlightValues],
  );
  const onPreview = props.onPreview;
  useEffect(
    /* 按修订标识上报工作副本，切换项目或分支时不会串用内容。 */ () =>
      onPreview(revisionId, previewContent),
    [onPreview, revisionId, previewContent],
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
  /** 立即缓存排序并写入草稿，等待用户统一提交为新版本。 */
  async function move(from: number, to: number) {
    if (ordering || from === to) return;
    setOrdering(true);
    try {
      const next = arrayMove(orderedHighlights, from, to).map(
        /* 逐项转换数据，保留当前业务需要的字段。 */ (h) => h.id,
      );
      order.update(next);
      await order.flush();
    } finally {
      setOrdering(false);
    }
  }
  return (
    <div className="editor">
      <VersionControl props={props} />
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
        <span
          className={`content-status ${props.hasLocalChanges || detail.working.drafts.length ? "pending" : "saved"}`}
        >
          {props.hasLocalChanges || detail.working.drafts.length ? (
            <CircleDashed size={12} aria-hidden="true" />
          ) : (
            <CircleCheck size={12} aria-hidden="true" />
          )}
          {props.hasLocalChanges
            ? "未提交的改动"
            : detail.working.drafts.length
              ? "未提交的改动"
              : "内容已提交"}
        </span>
        {revisionId !== detail.branch.head_revision && (
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
                        expected_head: detail.branch.head_revision,
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
            修改会自动保留为草稿。确认后点击“提交为新版本”，将本次编辑和排序合并为一个版本。
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
                        setMetaOpen(false);
                        props.onRefresh();
                      },
                    )
                }
              >
                完成编辑
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
            <div className="project-facts">
              {editor.value.period && (
                <span>
                  <CalendarDays size={13} aria-hidden="true" />
                  {editor.value.period}
                </span>
              )}
              {editor.value.role && (
                <span>
                  <BriefcaseBusiness size={13} aria-hidden="true" />
                  {editor.value.role}
                </span>
              )}
            </div>
            <div className="tech-stack" aria-label="项目技术栈">
              {editor.value.stack.map(
                /* 将技术栈拆成便于扫描的标签，保留原有顺序。 */ (
                  tech,
                  index,
                ) => (
                  <span className="tech-tag" key={`${tech}.${index}`}>
                    {tech}
                  </span>
                ),
              )}
            </div>
            <p className="project-description">
              {editor.value.description || "先分析项目，或手工补充描述。"}
            </p>
          </>
        )}
      </section>
      <div className="section-heading highlights-heading">
        <h3>
          项目亮点{" "}
          <span className="count-badge">{content.highlights.length}</span>
        </h3>
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
      {order.status && (
        <p className="subtle save-status" role="status">
          排序：{order.status}
        </p>
      )}
      {order.conflict && (
        <button
          onClick={
            /* 冲突时由用户选择载入远端排序，保留本机恢复副本。 */ () =>
              void order.reloadRemote()
          }
        >
          载入服务器排序草稿
        </button>
      )}
      {!content.highlights.length && (
        <div className="empty compact">
          <p>还没有项目亮点</p>
          <span>可以让 Codex 分析源码，也可以直接新增并编辑。</span>
        </div>
      )}
      <SortableList
        items={orderedHighlights.map(
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
        {orderedHighlights.map(
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
                      onPreview={updateHighlightPreview}
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
            <b>
              r{current.number} 的
              {snapshot.manifest.mode === "cited-files"
                ? "证据记录"
                : "历史快照"}
            </b>
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
          <p className="subtle">该版本尚无引用文件记录，不影响 AI 读取源码。</p>
        )}
        {snapshot &&
          detail.snapshots[0] &&
          snapshot.id !== detail.snapshots[0].id && (
            <p className="warning">
              已有更新的证据记录，当前经历保留原有引用。
            </p>
          )}
        <p className="subtle">AI 直接读取下方关联目录的当前源码。</p>
        {detail.project.roots.map(
          /* 按稳定标识生成对应的列表条目。 */ (root) => (
            <code className="path" key={root}>
              {root}
            </code>
          ),
        )}
        <details>
          <summary>重新绑定项目目录</summary>
          <PathInput
            label="来源路径（每行一个）"
            kind="folder"
            multiline
            value={roots}
            onChange={setRoots}
          />
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
              {detail.snapshots[0].manifest.mode === "cited-files"
                ? "最近证据记录 "
                : "历史快照 "}
              {new Date(detail.snapshots[0].created_at).toLocaleString()} ·{" "}
              {detail.snapshots[0].manifest.files.length}
              {detail.snapshots[0].manifest.mode === "cited-files"
                ? " 个引用文件"
                : " 个历史文件"}
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
                {detail.snapshots[0].manifest.mode === "cited-files"
                  ? "个引用文件未能留存，相关引文显示为待确认。"
                  : "个文件未纳入历史快照；新对话直接读取当前目录，不受旧快照范围限制。"}
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
