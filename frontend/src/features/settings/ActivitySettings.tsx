import { useEffect, useState } from "react";
import { api } from "../../shared/lib/api";
import {
  CATEGORIES,
  type ActivityCaptureSettings,
  type ActivityCategory,
} from "../activity/model";
import { DEFAULT_HIDDEN_RULES, hiddenRuleError } from "../activity/preferences";
import { localDayRange } from "../activity/useActivityTime";

/** 保存后端采集类别和页面过滤规则，并提供日志删除入口 */
export default function ActivitySettings({
  rules,
  onSave,
  onResetLayout,
  onDeleted,
}: {
  rules: string;
  onSave: (rules: string) => void;
  onResetLayout: () => void;
  onDeleted: () => void;
}) {
  const [draft, setDraft] = useState(rules);
  const [capture, setCapture] = useState<ActivityCaptureSettings | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);
  const [deleteScope, setDeleteScope] = useState("before_today");
  const [deleting, setDeleting] = useState(false);
  const [deleteResult, setDeleteResult] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const error = hiddenRuleError(draft);

  useEffect(() => {
    setSaved(false);
  }, [capture, draft]);

  useEffect(() => {
    const controller = new AbortController();
    setLoadError("");
    void api<ActivityCaptureSettings>(
      "/activity/settings",
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setCapture(value);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setLoadError(failure.message);
      });
    return () => controller.abort();
  }, [loadAttempt]);

  /** 后端保存成功后应用页面过滤，失败时保留输入以便重试 */
  async function saveSettings() {
    if (!capture || saving || error) return;
    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      await api<ActivityCaptureSettings>("/activity/settings", "PUT", capture);
      onSave(
        [
          ...new Set(
            draft
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean),
          ),
        ].join("\n"),
      );
      setSaved(true);
    } catch (failure) {
      setSaveError((failure as Error).message);
    } finally {
      setSaving(false);
    }
  }

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
    <section className="activity-settings" aria-label="日志设置">
      <fieldset
        className="activity-capture-settings"
        disabled={!capture || saving}
      >
        <legend>采集类别</legend>
        <div className="activity-capture-categories">
          {(Object.keys(CATEGORIES) as ActivityCategory[]).map((category) => (
            <label key={category}>
              <input
                type="checkbox"
                checked={capture?.categories.includes(category) ?? false}
                onChange={(event) => {
                  const checked = event.target.checked;
                  setCapture(
                    (current) =>
                      current && {
                        categories: checked
                          ? [...current.categories, category]
                          : current.categories.filter(
                              (value) => value !== category,
                            ),
                      },
                  );
                }}
              />
              {CATEGORIES[category]}
            </label>
          ))}
        </div>
        <div className="row">
          <button onClick={() => setCapture({ categories: ["ai"] })}>
            仅 AI 消息
          </button>
          <button
            onClick={() =>
              setCapture({
                categories: Object.keys(CATEGORIES) as ActivityCategory[],
              })
            }
          >
            全选
          </button>
        </div>
      </fieldset>
      {!capture && !loadError && <small role="status">正在读取采集设置…</small>}
      {loadError && (
        <div className="row">
          <span role="alert">读取采集设置失败：{loadError}</span>
          <button onClick={() => setLoadAttempt((value) => value + 1)}>
            重试
          </button>
        </div>
      )}
      <small>
        只记录勾选类别，默认仅 AI 消息。保存后立即生效，已有日志保留。
      </small>
      {capture?.categories.length === 0 && (
        <small role="status">保存后将暂停全部日志采集。</small>
      )}
      <label htmlFor="activity-hidden-rules">隐藏规则</label>
      <textarea
        id="activity-hidden-rules"
        value={draft}
        spellCheck={false}
        disabled={saving}
        onChange={(event) => setDraft(event.target.value)}
        rows={9}
      />
      <small>
        每行一条，支持路径、操作名、类型:事件和 *。只影响显示，不减少存储。
        警告、错误和 ≥1 秒操作仍显示。
      </small>
      {error && <span role="alert">{error}</span>}
      {saveError && <span role="alert">保存失败：{saveError}</span>}
      <div className="row">
        <button
          disabled={!capture || saving}
          onClick={() => {
            setDraft(DEFAULT_HIDDEN_RULES);
            setCapture({ categories: ["ai"] });
          }}
        >
          恢复默认
        </button>
        <button onClick={onResetLayout}>重置日志布局</button>
        <button
          className="primary"
          disabled={!!error || !capture || saving}
          onClick={() => void saveSettings()}
        >
          {saving ? "保存中…" : "保存日志设置"}
        </button>
      </div>
      {saved && <small role="status">日志设置已保存</small>}
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
        <small>永久删除所选范围，不影响简历和 AI 会话。</small>
        {deleteResult && <small role="status">{deleteResult}</small>}
        {deleteError && <span role="alert">{deleteError}</span>}
      </div>
    </section>
  );
}
