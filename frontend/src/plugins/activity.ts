export interface ActivityInput {
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
}

export interface ActivityPresentation {
  title: string;
  lines: readonly { label: string; text: string }[];
}

export interface ActivityPresenter {
  sources: readonly string[];
  present(event: Readonly<ActivityInput>): ActivityPresentation | null;
}

/** 检查日志展示的纯文本边界，拒绝过大输出和隐式 HTML */
export function activityPresentation(value: ActivityPresentation) {
  if (
    !value ||
    typeof value.title !== "string" ||
    !value.title.trim() ||
    value.title.length > 100 ||
    !Array.isArray(value.lines) ||
    value.lines.length > 50 ||
    value.lines.some(
      (line) =>
        !line ||
        typeof line.label !== "string" ||
        line.label.length > 100 ||
        typeof line.text !== "string" ||
        line.text.length > 4000,
    )
  )
    throw new Error("日志展示内容不符合契约。");
  return Object.freeze({
    title: value.title,
    lines: Object.freeze(
      value.lines.map(({ label, text }) => Object.freeze({ label, text })),
    ),
  });
}
