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
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import { api } from "../../shared/lib/api";
import { loadLocal, storage } from "../../shared/lib/storage";
import type {
  Highlight,
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
import { experienceContent } from "./visibility";
import { restoreBodyOrder } from "./bodyOrder";
import { fieldChanged } from "./changes";

/** 编辑经历元信息、来源和亮点，内容草稿和简历展示设置独立保存 */
export default function Editor(props: EditorProps) {
  const { detail, revisionId, run } = props;
  const current = detail.revisions.find((r) => r.id === revisionId)!;
  const snapshot = detail.revision_snapshot;
  const rootsKey = `rm.sources.${detail.project.id}`;
  const [roots, setRoots] = useState(() =>
    loadLocal(rootsKey, detail.project.roots.join("\n")),
  );
  useEffect(() => {
    if (roots === detail.project.roots.join("\n")) storage.removeItem(rootsKey);
    else storage.setItem(rootsKey, JSON.stringify(roots));
  }, [rootsKey, roots, detail.project.roots]);
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
    detail.working.drafts.find((d) => d.field === "meta")?.version ?? 0,
    /* 基本信息和正式版本比较，排序改回原位后立即清除待提交提示 */ (value) =>
      fieldChanged(value, current.content, "meta", props.visibility),
  );
  const order = useField(
    detail.project.id,
    revisionId,
    "order",
    content.highlights.map(
      /* 读取当前工作副本的亮点顺序 */ (point) => point.id,
    ),
    detail.working.drafts.find(
      /* 沿用排序草稿的并发版本 */ (draft) => draft.field === "order",
    )?.version ?? 0,
    /* 亮点顺序使用正式版本作为基线 */ (value) =>
      fieldChanged(value, current.content, "order"),
  );
  const [highlightValues, setHighlightValues] = useState<
    Record<string, Highlight>
  >({});
  /** 收集亮点实时输入，供父级组合预览使用 */
  const updateHighlightPreview = useCallback(
    /* 通过稳定回调收集亮点输入以避免预览循环更新 */ (point: Highlight) => {
      setHighlightValues(
        /* 值未变化时复用状态 */ (values) =>
          values[point.id] === point
            ? values
            : { ...values, [point.id]: point },
      );
    },
    [],
  );
  const orderedHighlights = useMemo(
    /* 恢复本机尚未写入服务器的排序，新亮点仍置于顶部 */ () =>
      [...content.highlights].sort(
        /* 按工作副本顺序显示卡片 */ (a, b) =>
          order.value.indexOf(a.id) - order.value.indexOf(b.id),
      ),
    [content.highlights, order.value],
  );
  const previewContent = useMemo(
    /* 合并元信息、亮点输入和排序，右侧始终使用编辑区的当前值 */ () => ({
      ...editor.value,
      highlights: orderedHighlights.map(
        /* 尚未挂载的条目使用已恢复的工作副本 */ (point) =>
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
    /* 按修订标识上报工作副本，切换项目或分支时不会串用内容 */ () =>
      onPreview(revisionId, previewContent),
    [onPreview, revisionId, previewContent],
  );
  const profileKey = `rm.profile.${detail.project.id}`;
  const [profile, setProfile] = useState<Profile>(() =>
    loadLocal(profileKey, detail.project.profile),
  );
  /** 更新本人贡献信息并保存本机恢复副本，等待用户正式保存 */
  function updateProfile(key: keyof Profile, value: string) {
    const next = { ...profile, [key]: value };
    setProfile(next);
    storage.setItem(profileKey, JSON.stringify(next));
  }
  /** 将排序缓存并保存为草稿 */
  async function move(from: number, to: number) {
    if (ordering || from === to) return;
    setOrdering(true);
    try {
      const next = arrayMove(orderedHighlights, from, to).map((h) => h.id);
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
              /* 确认前保留全部改动，先打开撤销确认 */ () =>
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
            onClick={() =>
              run(async () => {
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
              })
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
            /* 取消只关闭确认，草稿保持原状 */ () => setDiscardOpen(false)
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
          /* 排回原位时恢复基线表示以排除缺省顺序造成的虚假改动 */ (value) =>
            editor.update(
              restoreBodyOrder(value, current.content, props.visibility),
            )
        }
        status={editor.status}
        conflict={editor.conflict}
        onReload={editor.reloadRemote}
        onFinish={
          /* 完成编辑后保存草稿 */ async () => {
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
      {order.status && (
        <p className="subtle save-status" role="status">
          排序：{order.status}
        </p>
      )}
      {order.conflict && (
        <button
          onClick={
            /* 冲突时由用户选择载入远端排序，保留本机恢复副本 */ () =>
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
        items={orderedHighlights.map((item) => ({
          id: item.id,
          label: item.title || "未命名亮点",
        }))}
        disabled={ordering}
        onMove={
          /* 将排序落点交给当前业务的移动操作 */ (from, to) =>
            run(() => move(from, to))
        }
      >
        {orderedHighlights.map((item, index) => (
          <SortableItem
            key={`${item.id}.${detail.working.drafts.find((d) => d.field === `highlight:${item.id}`)?.version ?? 0}`}
            id={item.id}
            label={`亮点 ${item.title || "未命名亮点"}`}
            className="point-row"
          >
            {
              /* 将排序手柄嵌入对应业务条目的操作区 */ (handle) => (
                <>
                  <HighlightEditor
                    item={item}
                    draftVersion={
                      detail.working.drafts.find(
                        (d) => d.field === `highlight:${item.id}`,
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
                      onClick={() => run(() => move(index, index - 1))}
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
                      onClick={() => run(() => move(index, index + 1))}
                    >
                      <ArrowDown size={13} />
                    </button>
                  </div>
                </>
              )
            }
          </SortableItem>
        ))}
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
        {detail.project.roots.map((root) => (
          <code className="path" key={root}>
            {root}
          </code>
        ))}
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
              {detail.snapshots[0].manifest.mode === "cited-files"
                ? "最近证据记录 "
                : "历史快照 "}
              {new Date(detail.snapshots[0].created_at).toLocaleString()} ·{" "}
              {detail.snapshots[0].manifest.files.length}
              {detail.snapshots[0].manifest.mode === "cited-files"
                ? " 个引用文件"
                : " 个历史文件"}
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
              storage.removeItem(profileKey);
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
