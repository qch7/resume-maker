import { ArrowUpRight, History, Plus, Save } from "lucide-react";
import { useState } from "react";
import HistoryDialog from "./HistoryDialog";
import type { EditorProps } from "./types";

/** 将分支切换、历史树入口、版本发布放在紧凑工具栏中 */
export default function VersionControl({ props }: { props: EditorProps }) {
  const { detail, revisionId, run } = props;
  const [dialog, setDialog] = useState<"history" | "create" | null>(null);
  const current = detail.revision;
  const historical = detail.branch.head_revision !== revisionId;
  const pending = props.hasLocalChanges;
  const applied = props.usedRevision?.id === revisionId && !pending;
  return (
    <>
      <div className="version-control">
        <div className="version-navigation">
          <select
            className="branch-picker"
            aria-label="当前经历分支"
            value={detail.branch.id}
            onChange={
              /* 切到指定分支最新版本，原分支草稿先落盘 */ (event) => {
                const branch = detail.branches.find(
                  (item) => item.id === event.target.value,
                );
                if (branch) props.onRevision(branch.head_revision);
              }
            }
          >
            {detail.branches.map(
              /* 为每个命名分支生成可选项 */ (branch) => (
                <option key={branch.id} value={branch.id}>
                  {branch.name}
                  {branch.is_default ? " · 主分支" : ""}
                </option>
              ),
            )}
          </select>
          <button
            className="history-trigger"
            aria-label="查看经历历史树"
            onClick={() => setDialog("history")}
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
              /* 直接打开从当前节点创建分支的表单 */ () => setDialog("create")
            }
          >
            <Plus size={18} />
          </button>
        </div>
        <div className="version-actions" data-guide="experience-use">
          <button
            data-guide="experience-save"
            className="primary"
            disabled={props.saving || applied || (historical && pending)}
            title={
              historical && pending
                ? "先创建分支或回到该分支最新版本再保存"
                : "保存经历版本并更新当前简历草稿，其他简历保留原版本"
            }
            onClick={
              /* 历史版本直接引用，最新版本先保存再应用本次返回的版本 */ () => {
                if (historical) run(async () => props.onUseVersion());
                else void props.onSave(true);
              }
            }
          >
            <Save size={14} aria-hidden="true" />
            {props.saving
              ? "正在保存…"
              : applied
                ? "已用于当前简历"
                : pending
                  ? "保存并用于当前简历"
                  : "用于当前简历"}
            {!pending && !applied && (
              <ArrowUpRight size={14} aria-hidden="true" />
            )}
          </button>
          <button
            disabled={historical || props.saving || !pending}
            title="只保存经历版本，当前简历继续引用原版本"
            onClick={/* 保留独立积累经历版本的入口 */ () => void props.onSave()}
          >
            仅保存版本
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
              /* 回到当前分支最新版本，草稿保持各自独立 */ () =>
                props.onRevision(detail.branch.head_revision)
            }
          >
            回到分支最新版本
          </button>
          <button
            className="text-button"
            onClick={
              /* 从历史节点继续发展独立版本线 */ () => setDialog("create")
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
          onClose={/* 关闭历史窗口并恢复编辑区焦点 */ () => setDialog(null)}
        />
      )}
    </>
  );
}
