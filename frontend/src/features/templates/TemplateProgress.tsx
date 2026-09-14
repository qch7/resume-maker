import { Activity, CheckCircle2, LoaderCircle, X } from "lucide-react";
import type { TemplateProgressData } from "./types";

/** 将真实累计时间显示为便于阅读的分秒，不推测完成百分比。 */
export function duration(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return seconds >= 60
    ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
    : `${seconds} 秒`;
}

/** 展示 Codex 公开活动、实际轮次和耗时，结束后保留可展开的执行记录。 */
export default function TemplateProgress({
  data,
  busy,
  onCancel,
}: {
  data: TemplateProgressData;
  busy: boolean;
  onCancel: () => void;
}) {
  const running = data.status === "running";
  const latest = data.events.at(-1);
  const quiet = running && data.elapsed_ms - (latest?.elapsed_ms ?? 0) > 20000;
  return (
    <section className="template-live-progress" aria-label="Codex 实时动态">
      <div className="template-live-heading">
        {running ? (
          <LoaderCircle size={18} className="template-spinner" />
        ) : data.status === "completed" ? (
          <CheckCircle2 size={18} />
        ) : (
          <Activity size={18} />
        )}
        <div role="status">
          <strong>
            {data.reused
              ? "已复用识别结果"
              : running
                ? "Codex 正在适配模板"
                : data.status === "completed"
                  ? "模板识别完成"
                  : data.status === "cancelled"
                    ? "识别已取消"
                    : "识别未完成"}
          </strong>
          <span>{data.activity}</span>
        </div>
        <span className="template-live-time">
          {data.round > 0 && `第 ${data.round} 轮 · `}已用{" "}
          {duration(data.elapsed_ms)}
        </span>
        {running && (
          <button disabled={busy} onClick={onCancel}>
            <X size={14} />
            取消
          </button>
        )}
      </div>
      <details open={running}>
        <summary>
          Codex 实时动态
          {!running && data.events.length > 0
            ? ` · ${data.events.length} 条记录`
            : ""}
        </summary>
        {quiet && (
          <p className="subtle">
            Codex 仍在处理，最近{" "}
            {duration(data.elapsed_ms - (latest?.elapsed_ms ?? 0))}{" "}
            没有新的公开活动。
          </p>
        )}
        <ol className="template-live-events" aria-label="执行记录">
          {[...data.events].reverse().map(
            /* 最新活动优先展示，编号在增量重连后保持稳定。 */ (event) => (
              <li key={event.id}>
                <time>{duration(event.elapsed_ms)}</time>
                <span>{event.text}</span>
              </li>
            ),
          )}
        </ol>
        {data.usage.input_tokens !== undefined && (
          <p className="template-live-usage">
            累计输入 {data.usage.input_tokens.toLocaleString()} · 其中缓存{" "}
            {data.usage.cached_input_tokens?.toLocaleString() ?? 0} · 输出{" "}
            {data.usage.output_tokens?.toLocaleString() ?? 0} tokens
          </p>
        )}
      </details>
    </section>
  );
}
