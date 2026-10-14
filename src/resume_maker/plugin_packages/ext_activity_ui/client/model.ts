import type { ActivityInput } from "@resume-maker/plugin-sdk/plugins/activity";

export { CATEGORIES } from "@resume-maker/plugin-sdk/plugins/activity";

export type ActivityEvent = ActivityInput;

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

/** 合并已排序的当前窗口，空增量复用引用，新增事件按持久游标去重并限制内存 */
export function mergeEvents(
  current: ActivityEvent[],
  incoming: ActivityEvent[],
  older = false,
  hiddenTraces: string[] = [],
): ActivityEvent[] {
  if (!incoming.length && !hiddenTraces.length && current.length <= 3000)
    return current;
  const hidden = new Set(hiddenTraces);
  if (!incoming.length && current.length <= 3000) {
    const visible = current.filter((event) => !isHiddenPolling(event, hidden));
    return visible.length === current.length ? current : visible;
  }
  const values = new Map(current.map((event) => [event.id, event]));
  for (const event of incoming) values.set(event.id, event);
  const sorted = [...values.values()]
    .filter((event) => !isHiddenPolling(event, hidden))
    .sort((a, b) => a.id - b.id);
  return older ? sorted.slice(0, 3000) : sorted.slice(-3000);
}

/** 成功响应到达后撤回普通轮询及读取步骤，保留慢操作、警告、错误 */
export function isHiddenPolling(event: ActivityEvent, hidden: Set<string>) {
  return (
    hidden.has(event.trace_id) &&
    event.level === "info" &&
    (event.duration_ms ?? 0) < 1000 &&
    (event.category === "api" ||
      (event.category === "service" &&
        ["started", "completed"].includes(event.event)))
  );
}

/** 执行阶段使用简短中文，分别展示本机原文、模型上下文 */
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
  return positionAt(Date.parse(event.created_at), first, last);
}

/** 共用一批日志的时间边界，同毫秒事件沿用居中的可选择位置 */
function positionAt(timestamp: number, first: number, last: number) {
  if (last <= first) return 50;
  return Math.max(
    0,
    Math.min(99.5, ((timestamp - first) / (last - first)) * 99.5),
  );
}

const TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  hour12: false,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  fractionalSecondDigits: 3,
};
const timeFormatter = new Intl.DateTimeFormat("zh-CN", TIME_OPTIONS);

/** 将时间显示为本机毫秒时间，完整日期在详情中保留 */
export function eventTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? date.toLocaleTimeString("zh-CN", TIME_OPTIONS)
    : timeFormatter.format(date);
}

interface IndexedActivity {
  event: ActivityEvent;
  index: number;
  position: number;
  time: string;
}

/** 一次归约分类、时间标签、轨道位置，滚动及选择变化直接复用当前窗口索引 */
export function indexEvents(events: ActivityEvent[]) {
  const byId = new Map<number, IndexedActivity>();
  const categories = new Map<string, IndexedActivity[]>();
  const first = Date.parse(events[0]?.created_at ?? "");
  const last = Date.parse(events.at(-1)?.created_at ?? "");
  events.forEach((event, index) => {
    const entry = {
      event,
      index,
      position: positionAt(Date.parse(event.created_at), first, last),
      time: eventTime(event.created_at),
    };
    byId.set(event.id, entry);
    const group = categories.get(event.category) ?? [];
    group.push(entry);
    categories.set(event.category, group);
  });
  return { byId, categories };
}
