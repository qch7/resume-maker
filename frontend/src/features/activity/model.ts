export const CATEGORIES = {
  api: "API",
  ai: "AI 消息",
  tool: "工具",
  task: "任务",
  service: "业务操作",
  system: "系统",
  client: "浏览器",
} as const;

export type ActivityEvent = {
  id: number;
  created_at: string;
  category: string;
  level: string;
  source: string;
  event: string;
  title: string;
  trace_id: string;
  span_id: string;
  parent_span_id: string;
  job_id: string;
  conversation_id: string;
  project_id: string;
  duration_ms: number | null;
  payload?: unknown;
};

export type ActivityPage = {
  events: ActivityEvent[];
  cursor: number;
  has_more: boolean;
  oldest: number;
  counts: Record<string, number>;
  total: number;
  write_failures: number;
  last_error: string;
  retention_days: number;
  max_records: number;
};

/** 按持久游标去重并保持时间顺序，限制当前页面内存占用 */
export function mergeEvents(
  current: ActivityEvent[],
  incoming: ActivityEvent[],
  older = false,
): ActivityEvent[] {
  const values = new Map(current.map((event) => [event.id, event]));
  for (const event of incoming) values.set(event.id, event);
  const sorted = [...values.values()].sort((a, b) => a.id - b.id);
  return older ? sorted.slice(0, 3000) : sorted.slice(-3000);
}

/** 以可见事件的真实时间定位轨道标记，同毫秒事件仍保留可选择位置 */
export function eventPosition(event: ActivityEvent, events: ActivityEvent[]) {
  const first = Date.parse(events[0]?.created_at ?? event.created_at);
  const last = Date.parse(events.at(-1)?.created_at ?? event.created_at);
  if (last <= first) return 50;
  return Math.max(
    0,
    Math.min(
      99.5,
      ((Date.parse(event.created_at) - first) / (last - first)) * 99.5,
    ),
  );
}

/** 将时间显示为本机毫秒时间，完整日期在详情中保留 */
export function eventTime(value: string) {
  return new Date(value).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}
