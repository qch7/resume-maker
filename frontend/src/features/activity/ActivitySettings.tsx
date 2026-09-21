import { useState } from "react";
import { DEFAULT_POLLING_PATHS, pollingPathError } from "./preferences";

/** 编辑轮询路径规则，保存后立即应用并作为下次进入日志的默认值 */
export default function ActivitySettings({
  paths,
  onSave,
  onClose,
  onResetLayout,
}: {
  paths: string;
  onSave: (paths: string) => void;
  onClose: () => void;
  onResetLayout: () => void;
}) {
  const [draft, setDraft] = useState(paths);
  const error = pollingPathError(draft);
  return (
    <div className="activity-settings" role="dialog" aria-label="日志设置">
      <label htmlFor="activity-polling-paths">轮询路径 · GET 200</label>
      <textarea
        id="activity-polling-paths"
        value={draft}
        spellCheck={false}
        onChange={(event) => setDraft(event.target.value)}
        rows={5}
      />
      <small>每行一条，支持 *；隐藏开关和尺寸自动保存。</small>
      {error && <span role="alert">{error}</span>}
      <div className="row">
        <button onClick={() => setDraft(DEFAULT_POLLING_PATHS)}>
          恢复路径
        </button>
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
