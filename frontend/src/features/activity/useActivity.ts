import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/lib/api";
import { mergeEvents, type ActivityEvent, type ActivityPage } from "./model";

/** 用串行增量请求跟随日志，筛选变化或离开页面时取消旧请求 */
export function useActivity(query: string, live: boolean) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [page, setPage] = useState<ActivityPage | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [olderLoading, setOlderLoading] = useState(false);
  const [hasOlder, setHasOlder] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const session = useRef<AbortController | null>(null);
  const historyRequest = useRef<{
    hidden: Set<string>;
    updates: Map<number, ActivityEvent>;
  } | null>(null);
  const liveRef = useRef(live);
  liveRef.current = live;
  useEffect(() => {
    const controller = new AbortController();
    session.current = controller;
    historyRequest.current = null;
    let timer: ReturnType<typeof setTimeout>;
    let cursor = 0;
    let initialized = false;
    setEvents([]);
    setLoading(true);
    setOlderLoading(false);
    setError("");
    setHasOlder(false);
    setPage(null);
    /** 请求下一批事件，积压时连续分页，暂停时保留已读游标 */
    async function poll() {
      let delay = 1500;
      if (!initialized || liveRef.current) {
        try {
          const result = await api<ActivityPage>(
            `/activity?${query}${initialized ? `&after=${cursor}` : ""}`,
            "GET",
            undefined,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          // 历史请求可能带回旧快照，保留同期撤回的链路直到该请求结束
          for (const trace of result.hidden_trace_ids)
            historyRequest.current?.hidden.add(trace);
          for (const update of result.updated_events ?? [])
            historyRequest.current?.updates.set(update.id, update);
          setEvents((current) =>
            mergeEvents(
              current,
              result.events,
              false,
              result.hidden_trace_ids,
              result.updated_events,
            ),
          );
          setPage(result);
          setError("");
          if (!initialized) setHasOlder(result.has_more);
          else if (result.has_more) delay = 30;
          cursor = result.cursor;
          initialized = true;
        } catch (failure) {
          if (!controller.signal.aborted) setError((failure as Error).message);
        } finally {
          if (!controller.signal.aborted) setLoading(false);
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, delay);
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [query, refresh]);

  /** 向前加载较早记录，后端过滤和当前筛选保持一致 */
  async function loadOlder() {
    const controller = session.current;
    if (!controller || historyRequest.current || !events.length) return;
    const hidden = new Set<string>();
    const updates = new Map<number, ActivityEvent>();
    const history = { hidden, updates };
    historyRequest.current = history;
    setOlderLoading(true);
    try {
      const result = await api<ActivityPage>(
        `/activity?${query}&before=${events[0].id}`,
        "GET",
        undefined,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setEvents((current) =>
        mergeEvents(
          current,
          result.events,
          true,
          [...hidden],
          [...updates.values()],
        ),
      );
      setHasOlder(result.has_more);
    } catch (failure) {
      if (!controller.signal.aborted) setError((failure as Error).message);
    } finally {
      if (historyRequest.current === history) historyRequest.current = null;
      if (!controller.signal.aborted) setOlderLoading(false);
    }
  }
  return {
    events,
    page,
    error,
    loading,
    olderLoading,
    hasOlder: hasOlder || (page?.total ?? 0) > 3000,
    loadOlder,
    refresh: () => setRefresh((value) => value + 1),
  };
}
