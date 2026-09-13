import { ArrowUpRight, GitBranch, History, Plus, Save } from "lucide-react";
import { useRef, useState } from "react";
import HistoryDialog from "./HistoryDialog";
import type { EditorProps } from "./types";

/** 将分支切换、历史树入口与版本发布放在紧凑工具栏中。 */
export default function VersionControl({ props }: { props: EditorProps }) {
  const { detail, revisionId, run } = props;
  const [dialog, setDialog] = useState<"history" | "create" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submission = useRef(false);
  const current = detail.revisions.find(
    /* 显示当前编辑的具体版本。 */ (revision) => revision.id === revisionId,
  )!;
  const historical = detail.branch.head_revision !== revisionId;
  const pending = props.hasLocalChanges || detail.working.drafts.length > 0;
  return (
    <>
      <div className="version-control">
        <div className="version-navigation">
          <label className="branch-picker">
            <span>
              <GitBranch size={14} /> 当前分支
            </span>
            <select
              aria-label="当前经历分支"
              value={detail.branch.id}
              onChange={
                /* 切到指定分支最新版本，原分支草稿先落盘。 */ (event) => {
                  const branch = detail.branches.find(
                    /* 查找用户选定的分支指针。 */ (item) =>
                      item.id === event.target.value,
                  );
                  if (branch) props.onRevision(branch.head_revision);
                }
              }
            >
              {detail.branches.map(
                /* 为每个命名分支生成可选项。 */ (branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name}
                    {branch.is_default ? " · 主分支" : ""}
                  </option>
                ),
              )}
            </select>
          </label>
          <button
            className="history-trigger"
            aria-label="查看经历历史树"
            onClick={
              /* 展开包含全部分支的历史树。 */ () => setDialog("history")
            }
          >
            <History size={16} />
            <span>
              r{current.number} · {historical ? "历史版本" : "最新版本"}
              {pending ? " · 未提交" : ""}
            </span>
          </button>
          <button
            className="icon-button"
            title="从当前版本创建分支"
            aria-label="新建经历分支"
            onClick={
              /* 直接打开从当前节点创建分支的表单。 */ () => setDialog("create")
            }
          >
            <Plus size={18} />
          </button>
        </div>
        <div className="version-actions">
          <button
            data-guide="experience-save"
            className="primary"
            disabled={historical || submitting || !pending}
            title={
              historical ? "先创建分支或回到该分支最新版本再保存" : undefined
            }
            onClick={
              /* 用户明确确认后才把所有草稿合并提交一次。 */ () =>
                run(
                  /* 阻止重复点击产生并行提交，失败时仍保留草稿。 */ async () => {
                    if (submission.current) return;
                    submission.current = true;
                    setSubmitting(true);
                    try {
                      await props.onSave("experience");
                    } finally {
                      submission.current = false;
                      setSubmitting(false);
                    }
                  },
                )
            }
          >
            <Save size={14} aria-hidden="true" />
            {submitting ? "正在提交…" : "提交为新版本"}
          </button>
          <button
            data-guide="experience-use"
            onClick={
              /* 将该保存版本用于当前简历，不移动其他分支。 */ () =>
                run(
                  /* 保留固定版本引用语义。 */ async () => props.onUseVersion(),
                )
            }
          >
            用于当前简历
            <ArrowUpRight size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
      {historical && (
        <div className="notice history-notice">
          <span>
            正在查看 {detail.branch.name}{" "}
            的历史版本。可从此版本创建分支，继续编辑。
          </span>
          <button
            className="text-button"
            onClick={
              /* 回到当前分支最新版本，草稿保持各自独立。 */ () =>
                props.onRevision(detail.branch.head_revision)
            }
          >
            回到分支最新版本
          </button>
          <button
            className="text-button"
            onClick={
              /* 从历史节点继续发展独立版本线。 */ () => setDialog("create")
            }
          >
            从此版本创建分支
          </button>
        </div>
      )}
      {dialog && (
        <HistoryDialog
          props={props}
          createInitially={dialog === "create"}
          onClose={/* 关闭历史窗口并恢复编辑区焦点。 */ () => setDialog(null)}
        />
      )}
    </>
  );
}
