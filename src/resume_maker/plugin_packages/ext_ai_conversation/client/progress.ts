export interface ProgressEvent {
  kind: string;
  created_at?: string;
  data: {
    text?: string;
    type?: string;
    input_tokens?: number;
    output_tokens?: number;
    files_read?: number;
    tool_calls?: number;
  };
}

export interface ProgressEntry {
  text: string;
  kind: string;
  at: number | null;
  count: number;
}

/** 只保留面向用户的进度摘要，忽略会话标识及未知内部事件 */
export function progressText(event: ProgressEvent) {
  if (
    event.kind === "status" ||
    (event.kind === "activity" &&
      ["material_read", "material_complete", "source_progress"].includes(
        event.data.type ?? "",
      ))
  )
    return event.data.text?.slice(0, 240) ?? "";
  if (event.kind === "usage") return "模型本轮处理已结束";
  if (event.kind === "error") return "任务遇到问题，请查看任务状态后重试";
  return "";
}

/** 连续相同反馈合并计数，详情最多保留最近二十条 */
export function appendProgress(
  previous: ProgressEntry[],
  event: ProgressEvent,
): ProgressEntry[] {
  const text = progressText(event);
  if (!text) return previous;
  const timestamp = Date.parse(event.created_at ?? "");
  const entry = {
    text,
    kind: event.kind,
    at: Number.isFinite(timestamp) ? timestamp : null,
    count: 1,
  };
  const last = previous.at(-1);
  return last?.text === text && last.kind === event.kind
    ? [...previous.slice(0, -1), { ...entry, count: last.count + 1 }]
    : [...previous.slice(-19), entry];
}

/** 用实际时间差显示等待时长，不估算任务完成比例 */
export function progressDuration(start: number, end: number) {
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  return seconds < 60
    ? `${seconds} 秒`
    : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}
