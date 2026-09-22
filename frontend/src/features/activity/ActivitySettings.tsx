import { useState } from "react";
import { api } from "../../shared/lib/api";
import { DEFAULT_HIDDEN_RULES, hiddenRuleError } from "./preferences";
import { localDayRange } from "./useActivityTime";

/** 配置日志过滤及布局，并提供确认后删除日志的入口 */
export default function ActivitySettings({
  rules,
  onSave,
  onClose,
  onResetLayout,
  onDeleted,
}: {
  rules: string;
  onSave: (rules: string) => void;
  onClose: () => void;
  onResetLayout: () => void;
  onDeleted: () => void;
}) {
  const [draft, setDraft] = useState(rules);
  const [deleteScope, setDeleteScope] = useState("before_today");
  const [deleting, setDeleting] = useState(false);
  const [deleteResult, setDeleteResult] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const error = hiddenRuleError(draft);

  /** 确认删除范围后清理日志，成功时刷新列表和详情 */
  async function deleteLogs() {
    if (deleting) return;
    const before =
      deleteScope === "before_today" ? new Date(localDayRange().since) : null;
    const scope = before ? `${before.toLocaleString()} 之前的日志` : "全部日志";
    if (
      !window.confirm(
        `永久删除${scope}？包括被筛选隐藏的记录，无法恢复。简历资料和 AI 会话不受影响。`,
      )
    )
      return;
    setDeleting(true);
    setDeleteResult("");
    setDeleteError("");
    try {
      const result = await api<{ deleted: number }>("/activity", "DELETE", {
        before: before?.toISOString() ?? null,
      });
      onDeleted();
      setDeleteResult(`已删除 ${result.deleted.toLocaleString()} 条日志`);
    } catch (failure) {
      setDeleteError((failure as Error).message);
    } finally {
      setDeleting(false);
    }
  }
  return (
    <div className="activity-settings" role="dialog" aria-label="日志设置">
      <label htmlFor="activity-hidden-rules">隐藏日志</label>
      <textarea
        id="activity-hidden-rules"
        value={draft}
        spellCheck={false}
        onChange={(event) => setDraft(event.target.value)}
        rows={9}
      />
      <small>
        每行一条，支持 *。路径默认 GET，也可填 POST /api/…、操作名或
        ai:turn.started。轮询保留响应，警告、错误和 ≥1 秒操作始终保留。
      </small>
      {error && <span role="alert">{error}</span>}
      <div className="row">
        <button onClick={() => setDraft(DEFAULT_HIDDEN_RULES)}>恢复默认</button>
        <button onClick={onResetLayout}>重置布局</button>
        <button onClick={onClose}>取消</button>
        <button
          disabled={!!error}
          onClick={() =>
            onSave(
              [
                ...new Set(
                  draft
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean),
                ),
              ].join("\n"),
            )
          }
        >
          保存
        </button>
      </div>
      <div className="activity-delete-settings">
        <label htmlFor="activity-delete-scope">删除日志</label>
        <div className="row">
          <select
            id="activity-delete-scope"
            value={deleteScope}
            disabled={deleting}
            onChange={(event) => {
              setDeleteScope(event.target.value);
              setDeleteResult("");
              setDeleteError("");
            }}
          >
            <option value="before_today">今天之前</option>
            <option value="all">全部日志</option>
          </select>
          <button
            className="danger"
            disabled={deleting}
            onClick={() => void deleteLogs()}
          >
            {deleting ? "删除中…" : "删除"}
          </button>
        </div>
        <small>含隐藏记录，删除后无法恢复；新活动仍会记录。</small>
        {deleteResult && <small role="status">{deleteResult}</small>}
        {deleteError && <span role="alert">{deleteError}</span>}
      </div>
    </div>
  );
}
