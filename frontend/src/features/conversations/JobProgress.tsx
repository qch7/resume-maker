import { useEffect, useState } from "react";
import { request } from "../../shared/lib/api";
import type { Job } from "../../shared/types/index";

/** 消费当前任务的 SSE 事件，展示最近进度并在卸载时取消连接。 */
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
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      const controller = new AbortController();
      void (
        /* 执行当前异步流程，保持请求结果与所属组件状态一致。 */ (async () => {
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
                  .find(
                    /* 定位与当前标识或条件匹配的条目。 */ (line) =>
                      line.startsWith("data: "),
                  );
                if (data) {
                  const event = JSON.parse(data.slice(6));
                  setEvents(
                    /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                      previous,
                    ) => [...previous.slice(-19), event],
                  );
                }
              }
            }
          } catch (error) {
            if (!controller.signal.aborted)
              setEvents(
                /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                  previous,
                ) => [
                  ...previous,
                  { kind: "error", data: { text: (error as Error).message } },
                ],
              );
          }
        })()
      );
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        controller.abort();
    },
    [job.id],
  );
  const last = [...events]
    .reverse()
    .find(/* 定位与当前标识或条件匹配的条目。 */ (e) => e.data.text);
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
        {events.map(
          /* 按稳定标识生成对应的列表条目。 */ (event, index) => (
            <div className="activity" key={index}>
              {event.data.text ??
                (event.kind === "usage"
                  ? `输入 ${event.data.input_tokens ?? "未知"} / 输出 ${event.data.output_tokens ?? "未知"} token`
                  : event.kind === "thread"
                    ? "会话已连接"
                    : (event.data.type ?? event.kind))}
            </div>
          ),
        )}
      </details>
    </div>
  );
}
