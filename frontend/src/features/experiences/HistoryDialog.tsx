import { GitBranch, GitCommitHorizontal, Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { api } from "../../shared/lib/api";
import { flushDrafts } from "../../shared/lib/draftRegistry";
import type { Branch, ProjectDetail } from "../../shared/types/index";
import type { EditorProps } from "./types";
import { historyGraph, revisionChanges, revisionOrigin } from "./history";

/** 在历史树中预览不可变版本，或从任意节点创建独立分支。 */
export default function HistoryDialog({
  props,
  createInitially,
  onClose,
}: {
  props: EditorProps;
  createInitially: boolean;
  onClose: () => void;
}) {
  const { revisionId } = props;
  const [detail, setDetail] = useState(props.detail);
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [selected, setSelected] = useState(revisionId);
  const [creating, setCreating] = useState(createInitially);
  const [name, setName] = useState("");
  const [includeDrafts, setIncludeDrafts] = useState(true);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const graph = historyGraph(
    detail.revisions,
    detail.branches,
    detail.uncommitted,
  );
  const current = graph.nodes.find(
    /* 草稿节点使用工作副本，正式节点仍使用不可变内容。 */ (node) =>
      node.revision.id === selected,
  )!.revision;
  const baseId = current.uncommitted ? current.parent_id! : current.id;
  const parent = detail.revisions.find(
    /* 展示可核对的分叉来源。 */ (revision) =>
      revision.id === current.parent_id,
  );
  const branch = detail.branches.find(
    /* 识别当前节点所属分支及其最新指针。 */ (item) =>
      item.id === current.branch_id,
  )!;

  useEffect(
    /* 使用原生模态焦点约束，关闭时归还焦点。 */ () => {
      const element = dialog.current;
      element?.showModal();
      return /* 卸载时释放原生模态状态。 */ () => element?.close();
    },
    [],
  );

  useEffect(
    /* 打开历史树时先同步输入，再读取所有分支的未提交工作副本。 */ () => {
      const controller = new AbortController();
      void flushDrafts()
        .then(
          /* 草稿落盘后读取最新树，避免漏掉刚输入但未防抖保存的内容。 */ () =>
            api<ProjectDetail>(
              `/projects/${props.detail.project.id}?revision_id=${revisionId}`,
              "GET",
              undefined,
              controller.signal,
            ),
        )
        .then(
          /* 首次打开优先展示当前工作副本，创建分支仍以正式版本为起点。 */ (
            fresh,
          ) => {
            if (controller.signal.aborted) return;
            setDetail(fresh);
            if (
              !createInitially &&
              fresh.uncommitted?.some(
                /* 检查当前基线是否存在真实改动。 */ (item) =>
                  item.base_revision === revisionId,
              )
            )
              setSelected(`working:${revisionId}`);
          },
        )
        .catch(
          /* 读取失败保留已有历史并展示原因。 */ (reason) => {
            if (!controller.signal.aborted)
              setError(
                reason instanceof Error
                  ? reason.message
                  : "无法读取未提交的改动。",
              );
          },
        )
        .finally(
          /* 结束初始化后允许选择、继续编辑或创建分支。 */ () => {
            if (!controller.signal.aborted) setBusy(false);
          },
        );
      return /* 关闭弹窗后取消读取，避免更新已卸载的窗口。 */ () =>
        controller.abort();
    },
    [props.detail.project.id, revisionId, createInitially],
  );

  /** 先落盘输入，再创建分支；错误留在表单中，保留用户填写的名称。 */
  async function create() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await flushDrafts();
      const result = await api<Branch>(
        `/projects/${detail.project.id}/branches`,
        "POST",
        {
          name: name.trim(),
          base_revision: baseId,
          include_drafts: includeDrafts,
        },
      );
      props.onRevision(result.head_revision);
      props.onRefresh();
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法创建分支。");
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <dialog
      ref={dialog}
      className="history-dialog"
      aria-labelledby={titleId}
      onCancel={
        /* 创建过程中保持弹窗，避免重复提交。 */ (event) => {
          if (busy) event.preventDefault();
          else onClose();
        }
      }
    >
      <header className="dialog-title history-title">
        <div>
          <h2 id={titleId}>
            <GitBranch size={20} /> 经历历史
          </h2>
          <p className="subtle">
            {detail.project.name} · {detail.branches.length} 个分支 ·{" "}
            {detail.revisions.length} 个版本
            {!!detail.uncommitted?.length &&
              ` · ${detail.uncommitted.length} 份未提交改动`}
          </p>
        </div>
        <button
          className="icon-button"
          aria-label="关闭经历历史"
          onClick={onClose}
          disabled={busy}
        >
          <X size={20} />
        </button>
      </header>
      <div className="history-layout">
        <div className="history-timeline" aria-label="经历版本历史树">
          <div
            className="history-graph"
            style={
              {
                "--graph-width": `${graph.width}px`,
                minHeight: graph.height,
              } as CSSProperties
            }
          >
            <svg
              className="history-lines"
              width={graph.width}
              height={graph.height}
              aria-hidden="true"
            >
              {graph.edges.map(
                /* 真实父子关系连线，分支交汇点保留颜色。 */ (edge) => (
                  <path
                    key={edge.from}
                    d={edge.path}
                    fill="none"
                    stroke={edge.color}
                    strokeWidth="2"
                    strokeDasharray={edge.uncommitted ? "5 4" : undefined}
                  />
                ),
              )}
              {graph.nodes.map(
                /* 用空心外环标识当前预览节点。 */ (node) => (
                  <g key={node.revision.id}>
                    {node.revision.id === selected && (
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r="9"
                        fill="var(--surface)"
                        stroke={node.color}
                        strokeWidth="2"
                      />
                    )}
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={node.revision.uncommitted ? "5" : "4"}
                      fill={
                        node.revision.uncommitted
                          ? "var(--surface)"
                          : node.color
                      }
                      stroke={node.color}
                      strokeWidth="2"
                    />
                  </g>
                ),
              )}
            </svg>
            {graph.nodes.map(
              /* 一行对应一个保存版本，按钮支持键盘选择。 */ ({
                revision,
                color,
              }) => {
                const atHead = detail.branches.some(
                  /* 在分支最新节点展示指针标签。 */ (item) =>
                    item.head_revision === revision.id,
                );
                return (
                  <button
                    key={revision.id}
                    className={`history-node ${revision.uncommitted ? "history-node-uncommitted" : ""} ${selected === revision.id ? "selected" : ""}`}
                    aria-pressed={selected === revision.id}
                    aria-label={
                      revision.uncommitted
                        ? `查看未提交的改动 ${revision.branch_name} 基于 r${revision.number}`
                        : `查看 r${revision.number} ${revision.branch_name} ${revisionOrigin(revision.origin)}`
                    }
                    disabled={busy}
                    onClick={
                      /* 切换预览节点并收起新建表单。 */ () => {
                        setSelected(revision.id);
                        setCreating(false);
                        setError("");
                      }
                    }
                  >
                    <span className="history-node-top">
                      <b>
                        {revision.uncommitted
                          ? "未提交的改动"
                          : `r${revision.number}`}
                      </b>
                      <span className="history-branch-tag" style={{ color }}>
                        <GitBranch size={12} />
                        {revision.branch_name}
                        {atHead ? " · 最新" : ""}
                      </span>
                      {revision.id === revisionId && (
                        <span className="subtle">当前查看</span>
                      )}
                    </span>
                    <span className="history-node-bottom">
                      {revision.uncommitted
                        ? `基于 r${revision.number} · 草稿自动保留`
                        : revisionOrigin(revision.origin)}{" "}
                      · {new Date(revision.created_at).toLocaleString()}
                    </span>
                  </button>
                );
              },
            )}
          </div>
        </div>
        <section className="history-preview" aria-label="版本详情">
          <div className="history-preview-actions">
            <button
              disabled={busy}
              onClick={
                /* 将该节点载入工作区，保留简历当前固定引用。 */ () => {
                  props.onRevision(baseId);
                  onClose();
                }
              }
            >
              {current.uncommitted ? "继续编辑" : "查看此版本"}
            </button>
            <button
              disabled={busy}
              onClick={
                /* 展开从所选节点创建分支的命名表单。 */ () =>
                  setCreating(!creating)
              }
            >
              <Plus size={15} />从 r{current.number} 创建分支
            </button>
          </div>
          <div className="history-preview-content">
            {creating && (
              <form
                className="history-branch-form"
                onSubmit={
                  /* 拦截浏览器表单跳转，通过事务接口创建分支。 */ (event) => {
                    event.preventDefault();
                    void create();
                  }
                }
              >
                <label>
                  分支名称
                  <input
                    autoFocus
                    required
                    maxLength={80}
                    placeholder="例如：后端岗位版"
                    value={name}
                    disabled={busy}
                    onChange={
                      /* 保留分支名称输入。 */ (event) =>
                        setName(event.target.value)
                    }
                  />
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={includeDrafts}
                    disabled={busy}
                    onChange={
                      /* 选择是否复制未发布修改，原稿继续保留。 */ (event) =>
                        setIncludeDrafts(event.target.checked)
                    }
                  />
                  复制此版本的未保存草稿
                </label>
                <p className="subtle">
                  从 r{current.number}{" "}
                  的保存内容开始。复制的草稿仍需另行保存，原分支保持不变。
                </p>
                {error && (
                  <p className="warning" role="alert">
                    {error}
                  </p>
                )}
                <button
                  className="primary"
                  disabled={busy || !name.trim()}
                  type="submit"
                >
                  {busy ? "正在创建…" : "创建并切换"}
                </button>
              </form>
            )}
            <div className="history-preview-heading">
              <GitCommitHorizontal size={20} />
              <h3>
                {current.uncommitted ? "未提交的改动" : `r${current.number}`}
              </h3>
              <span className="tag">{branch.name}</span>
            </div>
            <p className="subtle">
              {current.uncommitted
                ? `基于 r${current.number} · 尚未生成新版本`
                : revisionOrigin(current.origin)}{" "}
              · {new Date(current.created_at).toLocaleString()}
            </p>
            {error && (
              <p className="warning" role="alert">
                {error}
              </p>
            )}
            {parent && (
              <button
                className="text-button"
                disabled={busy}
                onClick={
                  /* 沿真实父关系向前查看历史。 */ () => {
                    setSelected(parent.id);
                    setCreating(false);
                  }
                }
              >
                父版本 r{parent.number} · {parent.branch_name}
              </button>
            )}
            <p className="history-change-summary">
              {current.origin === "branch"
                ? current.note
                : revisionChanges(current, parent).join(" · ")}
            </p>
            <div className="history-saved-content">
              <h3>{current.content.title}</h3>
              <p className="subtle">
                {[current.content.period, current.content.role]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <p>{current.content.stack.join(" · ")}</p>
              <p>{current.content.description || "尚未填写项目描述"}</p>
              {(current.content.custom_fields ?? []).map(
                /* 历史详情展示保存的自定义原文，隐藏项仍可核对和恢复。 */ (
                  field,
                ) => (
                  <p key={field.id}>
                    <b>{field.label || "未命名条目"}：</b>
                    {field.value || "未填写"}
                    {!field.visible && <span className="tag">已隐藏</span>}
                  </p>
                ),
              )}
              {current.content.highlights.map(
                /* 只展示保存内容，切换浏览不会改变原始版本。 */ (point) => (
                  <div className="history-highlight" key={point.id}>
                    <b>{point.title}</b>
                    <p>{point.text}</p>
                  </div>
                ),
              )}
            </div>
          </div>
        </section>
      </div>
      <footer className="history-footer subtle">
        虚线空心节点表示未提交的改动，关闭或重新打开后仍可继续编辑。点击“提交为新版本”后才生成正式版本。
      </footer>
    </dialog>,
    document.body,
  );
}
