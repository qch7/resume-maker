import { useState } from "react";
import {
  Activity,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  X,
} from "lucide-react";
import ResizeHandle from "../../shared/components/ResizeHandle";
import type { TemplateProgressData } from "./types";

/** 将真实累计时间显示为便于阅读的分秒，不推测完成百分比。 */
export function duration(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return seconds >= 60
    ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
    : `${seconds} 秒`;
}

/** 用紧凑状态栏展示当前动态或已保存的识别记录，展开后允许调整记录区高度。 */
export default function TemplateProgress({
  data,
  busy,
  height,
  maxHeight,
  onResize,
  onReset,
  onCancel,
}: {
  data: TemplateProgressData;
  busy: boolean;
  height: number;
  maxHeight: number;
  onResize: (value: number) => void;
  onReset: () => void;
  onCancel: () => void;
}) {
  const running = data.status === "running";
  const [expanded, setExpanded] = useState<boolean | null>(null);
  const latest = data.events.at(-1);
  const quiet = running && data.elapsed_ms - (latest?.elapsed_ms ?? 0) > 20000;
  const recorded =
    data.events.length > 0 ||
    data.round > 0 ||
    data.elapsed_ms > 0 ||
    data.usage.input_tokens !== undefined;
  const title = data.from_library
    ? "已加载模板"
    : running
      ? data.phase === "prepare"
        ? "正在自动整理"
        : "Codex 正在适配"
      : data.reused
        ? "已复用识别结果"
        : data.status === "completed"
          ? "识别完成"
          : data.status === "cancelled"
            ? "识别已取消"
            : "识别未完成";
  const canExpand = recorded || running;
  const showEvents = (expanded ?? running) && canExpand;
  return (
    <section className="template-live-progress" aria-label="模板识别动态">
      <div className="template-live-heading">
        {running ? (
          <LoaderCircle size={16} className="template-spinner" />
        ) : data.status === "completed" ? (
          <CheckCircle2 size={16} />
        ) : (
          <Activity size={16} />
        )}
        <strong role="status">{title}</strong>
        {running && (
          <span className="template-live-activity" title={data.activity}>
            {data.activity}
          </span>
        )}
        {recorded || running ? (
          <span className="template-live-time">
            {data.round > 0 && `${data.round} 轮 · `}
            {duration(data.elapsed_ms)}
          </span>
        ) : (
          <span className="template-live-time">未留存识别记录</span>
        )}
        {canExpand && (
          <button
            className="template-progress-toggle"
            aria-expanded={showEvents}
            onClick={
              /* 展开状态独立于轮询更新，保留用户主动收起的选择。 */ () =>
                setExpanded(!showEvents)
            }
          >
            {showEvents ? (
              <ChevronDown size={14} />
            ) : (
              <ChevronRight size={14} />
            )}
            {running ? "实时动态" : "识别记录"}
            {data.events.length > 0 && ` · ${data.events.length}`}
          </button>
        )}
        {running && (
          <button disabled={busy} onClick={onCancel}>
            <X size={14} />
            取消
          </button>
        )}
      </div>
      {showEvents && (
        <>
          <div className="template-live-body" style={{ height }}>
            {quiet && (
              <p className="subtle">
                Codex 仍在处理，最近{" "}
                {duration(data.elapsed_ms - (latest?.elapsed_ms ?? 0))}{" "}
                没有新的公开活动。
              </p>
            )}
            <ol className="template-live-events" aria-label="执行记录">
              {[...data.events].reverse().map(
                /* 最新活动优先展示，编号与原识别时的耗时保持不变。 */ (
                  event,
                ) => (
                  <li key={event.id}>
                    <time>{duration(event.elapsed_ms)}</time>
                    <span>{event.text}</span>
                  </li>
                ),
              )}
            </ol>
            {data.usage.input_tokens !== undefined && (
              <p className="template-live-usage">
                输入 {data.usage.input_tokens.toLocaleString()} · 缓存{" "}
                {data.usage.cached_input_tokens?.toLocaleString() ?? 0} · 输出{" "}
                {data.usage.output_tokens?.toLocaleString() ?? 0} tokens
              </p>
            )}
          </div>
          <ResizeHandle
            className="template-progress-resize"
            label="调整识别记录区高度"
            axis="y"
            value={height}
            min={72}
            max={maxHeight}
            onChange={onResize}
            onReset={onReset}
          />
        </>
      )}
    </section>
  );
}
