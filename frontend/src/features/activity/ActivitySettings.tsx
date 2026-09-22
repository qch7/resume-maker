import { useState } from "react";
import { DEFAULT_HIDDEN_RULES, hiddenRuleError } from "./preferences";

/** 配置例行维护和轮询过滤，保存为下次进入日志的默认值 */
export default function ActivitySettings({
  rules,
  onSave,
  onClose,
  onResetLayout,
}: {
  rules: string;
  onSave: (rules: string) => void;
  onClose: () => void;
  onResetLayout: () => void;
}) {
  const [draft, setDraft] = useState(rules);
  const error = hiddenRuleError(draft);
  return (
    <div className="activity-settings" role="dialog" aria-label="日志设置">
      <label htmlFor="activity-hidden-rules">隐藏日志</label>
      <textarea
        id="activity-hidden-rules"
        value={draft}
        spellCheck={false}
        onChange={(event) => setDraft(event.target.value)}
        rows={6}
      />
      <small>每行填写 API 路径或操作名，支持 *；保留警告和错误。</small>
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
    </div>
  );
}
