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
  hidden_trace_ids: string[];
};

/** 按持久游标去重并保持时间顺序，限制当前页面内存占用 */
export function mergeEvents(
  current: ActivityEvent[],
  incoming: ActivityEvent[],
  older = false,
  hiddenTraces: string[] = [],
): ActivityEvent[] {
  const hidden = new Set(hiddenTraces);
  const values = new Map(current.map((event) => [event.id, event]));
  for (const event of incoming) values.set(event.id, event);
  const sorted = [...values.values()]
    .filter((event) => !isHiddenPolling(event, hidden))
    .sort((a, b) => a.id - b.id);
  return older ? sorted.slice(0, 3000) : sorted.slice(-3000);
}

/** 成功响应到达后撤回重复步骤，保留响应、慢操作、警告和错误 */
export function isHiddenPolling(event: ActivityEvent, hidden: Set<string>) {
  return (
    hidden.has(event.trace_id) &&
    event.level === "info" &&
    ((event.category === "api" && event.event !== "response") ||
      (event.category === "service" &&
        ["started", "completed"].includes(event.event) &&
        (event.duration_ms ?? 0) < 1000))
  );
}

/** 将执行阶段改为简短中文，区分本机原文和模型上下文 */
export function eventPhase(event: ActivityEvent) {
  if (event.source === "provider.run_structured") {
    if (event.event === "started") return "原始输入";
    if (event.event === "completed") return "本机还原";
  }
  const labels: Record<string, string> = {
    request: "请求",
    response: "响应",
    started: "开始",
    completed: "完成",
    failed: "失败",
    context: "脱敏输入",
    system: "系统指令",
    status: "进度",
    "thread.started": "会话开始",
    "turn.started": "轮次开始",
    "turn.completed": "轮次完成",
    "item.started": "消息开始",
    "item.completed": "消息完成",
  };
  return labels[event.event] ?? event.event;
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
