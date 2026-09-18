import PathInput from "../../shared/components/PathInput";
import { arrayMove } from "@dnd-kit/sortable";
import {
  ArrowDown,
  ArrowUp,
  CircleCheck,
  CircleDashed,
  Plus,
  Undo2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import { api } from "../../shared/lib/api";
import { loadLocal } from "../../shared/lib/storage";
import type {
  Highlight,
  Experience,
  Meta,
  Profile,
  Revision,
} from "../../shared/types/index";
import HighlightEditor from "./HighlightEditor";
import MetaEditor from "./MetaEditor";
import DiscardChangesDialog from "./DiscardChangesDialog";
import VersionControl from "./VersionControl";
import type { EditorProps } from "./types";
import { useField } from "./useField";
import { experienceContent, separateMetaVisibility } from "./visibility";
import { restoreBodyOrder } from "./bodyOrder";
import { fieldChanged } from "./changes";

/** 将旧版元信息草稿中的显隐转到当前简历，再挂载正常编辑器以避免并发写入。 */
export default function Editor(props: EditorProps) {
  const [migration] = useState(
    /* 优先保留尚未同步的本机输入，整段 AI 草稿作为元信息的实际基线。 */ () => {
      const { detail, revisionId } = props;
      const key = `rm.field.${detail.project.id}.${revisionId}.meta`;
      const cached = loadLocal<{ value: Meta; version: number } | null>(
        key,
        null,
      );
      const draft = detail.working.drafts.find(
        /* 查找旧元信息草稿。 */ (item) => item.field === "meta",
      );
      if (!cached && !draft) return null;
      const base =
        (detail.working.drafts.find(
          /* 整段草稿先于元信息覆盖。 */ (item) => item.field === "experience",
        )?.value as Experience | undefined) ??
        detail.revisions.find(
          /* 读取当前不可变版本。 */ (item) => item.id === revisionId,
        )!.content;
      const meta = cached?.value ?? detail.working.content;
      const separated = separateMetaVisibility(base, meta, props.visibility);
      return separated.migrated ||
        separated.normalizedOrder ||
        !separated.contentChanged
        ? {
            ...separated,
            key,
            cached,
            draft,
            version: cached?.version ?? draft?.version ?? 0,
          }
        : null;
    },
  );
  const pending = useRef<Promise<void> | null>(null);
  const [error, setError] = useState("");
  useEffect(
    /* 本次挂载只执行一次转换；旧值先保留到恢复副本，失败不会丢失输入。 */ () => {
      if (!migration) return;
      let active = true;
      if (!pending.current)
        pending.current =
          /* 先保留到简历草稿，再以原版本号清理项目草稿。 */ (async () => {
            if (migration.migrated)
              props.onVisibility(migration.visibility, true);
            const original = localStorage.getItem(migration.key);
            if (original)
              localStorage.setItem(`${migration.key}.recovery`, original);
            const path = `/projects/${props.detail.project.id}/draft`;
            if (migration.contentChanged) {
              await api(path, "PUT", {
                base_revision: props.revisionId,
                field: "meta",
                value: migration.meta,
                version: migration.version,
              });
            } else if (migration.draft) {
              await api(`${path}/discard`, "POST", {
                base_revision: props.revisionId,
                field: "meta",
                version: migration.version,
              });
            }
            localStorage.removeItem(migration.key);
          })();
      void pending.current.then(
        /* 刷新后挂载已分离显隐的工作副本，纯显隐修改不再提示提交版本。 */ () => {
          if (active) props.onRefresh();
        },
        /* 保留原草稿，明确显示并发或网络错误。 */ (failure: Error) => {
          if (active) setError(failure.message);
        },
      );
      return /* 离开项目后不让迟到结果刷新其他项目。 */ () => {
        active = false;
      };
      // 转换只属于本次挂载的项目与版本，重新读取详情时由外层 key 重新创建。
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [migration],
  );
  if (migration)
    return error ? (
      <div className="error-panel" role="alert">
        {error}
        <button onClick={props.onRefresh}>刷新后重试</button>
      </div>
    ) : (
      <p className="subtle" role="status">
        正在更新显示设置…
      </p>
    );
  return <ExperienceEditor {...props} />;
}

/** 编辑经历元信息、来源和亮点，内容草稿与简历展示设置独立保存。 */
function ExperienceEditor(props: EditorProps) {
  const { detail, revisionId, run } = props;
  const current = detail.revisions.find(
    /* 定位与当前标识或条件匹配的条目。 */ (r) => r.id === revisionId,
  )!;
  const snapshot = detail.revision_snapshot;
  const [roots, setRoots] = useState(detail.project.roots.join("\n"));
  const content = detail.working.content;
  const [ordering, setOrdering] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const meta: Meta = {
    title: content.title,
    period: content.period,
    role: content.role,
    stack: content.stack,
    description: content.description,
    hidden_fields: content.hidden_fields ?? [],
    custom_fields: content.custom_fields ?? [],
    body_order: content.body_order ?? null,
  };
  const editor = useField(
    detail.project.id,
    revisionId,
    "meta",
    meta,
    detail.working.drafts.find(
      /* 定位与当前标识或条件匹配的条目。 */ (d) => d.field === "meta",
    )?.version ?? 0,
    /* 基本信息与正式版本比较，排序改回原位后立即清除待提交提示。 */ (value) =>
      fieldChanged(value, current.content, "meta", props.visibility),
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
    /* 亮点顺序使用正式版本作为基线。 */ (value) =>
      fieldChanged(value, current.content, "order"),
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
  const pendingChanges =
    experienceContent(previewContent, props.visibility) !==
    experienceContent(current.content, props.visibility);
  useEffect(
    /* 按修订标识上报工作副本，切换项目或分支时不会串用内容。 */ () =>
      onPreview(revisionId, previewContent),
    [onPreview, revisionId, previewContent],
  );
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
      <VersionControl props={{ ...props, hasLocalChanges: pendingChanges }} />
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
          className={`content-status ${pendingChanges ? "pending" : "saved"}`}
        >
          {pendingChanges ? (
            <CircleDashed size={12} aria-hidden="true" />
          ) : (
            <CircleCheck size={12} aria-hidden="true" />
          )}
          {pendingChanges ? "未提交的改动" : "内容已提交"}
        </span>
        {pendingChanges && (
          <button
            className="text-button"
            onClick={
              /* 确认前保留全部改动，先打开撤销确认。 */ () =>
                setDiscardOpen(true)
            }
          >
            <Undo2 size={13} />
            撤销改动
          </button>
        )}
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
      {discardOpen && (
        <DiscardChangesDialog
          projectId={detail.project.id}
          revisionId={revisionId}
          number={current.number}
          onClose={
            /* 取消只关闭确认，草稿保持原状。 */ () => setDiscardOpen(false)
          }
          onConfirm={props.onDiscard}
        />
      )}
      <MetaEditor
        definitions={props.definitions}
        value={editor.value}
        visibility={props.visibility}
        onVisibility={props.onVisibility}
        onChange={
          /* 排回原位还原基线表示，避免旧版缺省顺序变成虚假改动。 */ (value) =>
            editor.update(
              restoreBodyOrder(value, current.content, props.visibility),
            )
        }
        status={editor.status}
        conflict={editor.conflict}
        onReload={editor.reloadRemote}
        onFinish={
          /* 完成编辑只落盘草稿，正式版本仍由统一提交按钮生成。 */ async () => {
            await editor.flush();
            props.onRefresh();
          }
        }
      />
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
