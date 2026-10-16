import { useEffect, useState } from "react";
import { request } from "@resume-maker/plugin-sdk/shared/lib/api";
import type { Job } from "@resume-maker/plugin-sdk/shared/types/index";
import {
  appendProgress,
  progressDuration,
  type ProgressEntry,
} from "./progress";

/** 消费当前任务的 SSE 事件，展示最近进度并在卸载时取消连接 */
export default function JobProgress({ job }: { job: Job }) {
  const [events, setEvents] = useState<ProgressEntry[]>([]);
  const [sourceProgress, setSourceProgress] = useState<{
    files: number;
    calls: number;
  } | null>(null);
  const [openedAt] = useState(Date.now);
  const [clock, setClock] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await request(`/jobs/${job.id}/events`, {
          signal: controller.signal,
        });
        const reader = response.body!.getReader(),
          decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() ?? "";
          for (const chunk of chunks) {
            if (chunk.includes("event: done")) continue;
            const data = chunk
              .split("\n")
              .find((line) => line.startsWith("data: "));
            if (data) {
              const event = JSON.parse(data.slice(6));
              setEvents((previous) => appendProgress(previous, event));
              if (
                event.data.type === "source_progress" &&
                Number.isSafeInteger(event.data.files_read) &&
                event.data.files_read >= 0 &&
                Number.isSafeInteger(event.data.tool_calls) &&
                event.data.tool_calls >= 0
              )
                setSourceProgress({
                  files: event.data.files_read,
                  calls: event.data.tool_calls,
                });
            }
          }
        }
      } catch {
        if (!controller.signal.aborted)
          setEvents((previous) =>
            appendProgress(previous, {
              kind: "error",
              data: {},
            }),
          );
      }
    })();
    return () => controller.abort();
  }, [job.id]);
  const last = events.at(-1);
  const timestamp = Date.parse(job.started_at ?? job.created_at ?? "");
  const startedAt = Number.isFinite(timestamp) ? timestamp : openedAt;
  return (
    <div className="job-progress">
      <div className="row">
        <span className="pulse" />
        <span role="status">
          当前阶段：
          {job.status === "queued"
            ? "任务排队中"
            : (last?.text ?? "正在准备分析")}
        </span>
      </div>
      {sourceProgress && (
        <p className="subtle">
          已读取 {sourceProgress.files} 个源码文件 · 完成 {sourceProgress.calls}{" "}
          次源码工具调用
        </p>
      )}
      <p className="subtle" aria-live="off">
        已用 {progressDuration(startedAt, clock)} ·{" "}
        {last?.at !== null && last?.at !== undefined
          ? `最近进展：${progressDuration(last.at, clock)}前`
          : "等待首条进展"}
      </p>
      <details>
        <summary>查看最近进展（最多 20 条）</summary>
        {events.map((event, index) => (
          <div className="activity" key={index}>
            {event.text}
            {event.count > 1 ? `（连续 ${event.count} 次）` : ""}
          </div>
        ))}
      </details>
    </div>
  );
}
