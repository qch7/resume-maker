import { useEffect, useState } from "react";
import { request } from "../../shared/lib/api";
import type { Job } from "../../shared/types/index";

/** 消费当前任务的 SSE 事件，展示最近进度并在卸载时取消连接 */
export default function JobProgress({ job }: { job: Job }) {
  const [events, setEvents] = useState<
    {
      kind: string;
      data: {
        text?: string;
        type?: string;
        input_tokens?: number;
        output_tokens?: number;
      };
    }[]
  >([]);
  useEffect(() => {
    const controller = new AbortController();
    void (
      /* 执行当前异步流程，保持请求结果和所属组件状态一致 */ (async () => {
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
                setEvents((previous) => [...previous.slice(-19), event]);
              }
            }
          }
        } catch (error) {
          if (!controller.signal.aborted)
            setEvents((previous) => [
              ...previous,
              { kind: "error", data: { text: (error as Error).message } },
            ]);
        }
      })()
    );
    return () => controller.abort();
  }, [job.id]);
  const last = [...events].reverse().find((e) => e.data.text);
  return (
    <div className="job-progress">
      <div className="row">
        <span className="pulse" />
        <span>
          {job.status === "queued"
            ? "任务排队中"
            : (last?.data.text ?? "正在连接 Codex")}
        </span>
      </div>
      <details>
        <summary>查看执行过程</summary>
        {events.map((event, index) => (
          <div className="activity" key={index}>
            {event.data.text ??
              (event.kind === "usage"
                ? `输入 ${event.data.input_tokens ?? "未知"} / 输出 ${event.data.output_tokens ?? "未知"} token`
                : event.kind === "thread"
                  ? "会话已连接"
                  : (event.data.type ?? event.kind))}
          </div>
        ))}
      </details>
    </div>
  );
}
