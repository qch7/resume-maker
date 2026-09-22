import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity as ActivityIcon,
  ArrowDown,
  Download,
  Pause,
  Play,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { api, download } from "../../shared/lib/api";
import ResizeHandle from "../../shared/components/ResizeHandle";
import { useElementSize } from "../../shared/hooks/useElementSize";
import { clamp } from "../../shared/lib/layout";
import { loadLocal } from "../../shared/lib/storage";
import ActivitySettings from "./ActivitySettings";
import {
  DEFAULT_ACTIVITY_PREFERENCES,
  restoreActivityPreferences,
  type ActivityPreferences,
} from "./preferences";
import {
  CATEGORIES,
  eventPosition,
  eventTime,
  isHiddenPolling,
  type ActivityEvent,
} from "./model";
import { useActivity } from "./useActivity";

const ROW_HEIGHT = 32;

/** 在独立全宽区域展示统一活动轨道、实时列表和单条详情 */
export default function Activity() {
  const [preferences, setPreferences] = useState(() =>
    restoreActivityPreferences(
      loadLocal<Partial<ActivityPreferences> | null>("rm.activity", null),
    ),
  );
  const [settings, setSettings] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [category, setCategory] = useState("");
  const [level, setLevel] = useState("");
  const [search, setSearch] = useState("");
  const [keyword, setKeyword] = useState("");
  const [trace, setTrace] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [live, setLive] = useState(true);
  const [follow, setFollow] = useState(true);
  const [selected, setSelected] = useState<ActivityEvent | null>(null);
  const [actionError, setActionError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [scrollTop, setScrollTop] = useState(0);
  const scroll = useRef<HTMLDivElement>(null);
  const panels = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const panelsSize = useElementSize(panels);
  const bodySize = useElementSize(body);
  const listSize = useElementSize(scroll);
  const stacked = panelsSize.width < 700;
  const overviewMax = Math.max(
    32,
    panelsSize.height - (stacked && selected ? 240 : 160),
  );
  const overviewHeight = clamp(preferences.overviewHeight, 32, overviewMax);
  const detailMax = Math.max(
    stacked ? 80 : 260,
    stacked ? bodySize.height - 86 : bodySize.width - 266,
  );
  const detailSize = clamp(
    stacked ? preferences.detailHeight : preferences.detailWidth,
    stacked ? 80 : 260,
    detailMax,
  );
  useEffect(() => {
    try {
      localStorage.setItem("rm.activity", JSON.stringify(preferences));
    } catch {
      setActionError("浏览器无法保存日志设置");
    }
  }, [preferences]);

  /** 保存单项偏好，窗口缩小时只约束显示尺寸 */
  function resize(
    key: "overviewHeight" | "detailWidth" | "detailHeight",
    value: number,
  ) {
    setPreferences((current) => ({ ...current, [key]: value }));
  }
  useEffect(() => {
    const timer = setTimeout(() => setKeyword(search), 300);
    return () => clearTimeout(timer);
  }, [search]);
  const query = useMemo(() => {
    const params = new URLSearchParams({
      category,
      level,
      q: keyword,
      trace_id: trace,
      hide_polling: String(preferences.hidePolling),
      hide_maintenance: String(preferences.hideMaintenance),
      polling_paths: preferences.pollingPaths,
    });
    if (since) params.set("since", new Date(since).toISOString());
    if (until) params.set("until", new Date(until).toISOString());
    return params.toString();
  }, [
    category,
    level,
    keyword,
    trace,
    since,
    until,
    preferences.hidePolling,
    preferences.hideMaintenance,
    preferences.pollingPaths,
  ]);
  const feed = useActivity(query, live);
  const { events, page } = feed;
  useEffect(() => {
    if (selected && isHiddenPolling(selected, new Set(page?.hidden_trace_ids)))
      setSelected(null);
  }, [page, selected]);
  useEffect(() => {
    if (follow && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [events, follow]);
  useEffect(() => {
    setSelected(null);
    setScrollTop(0);
    if (scroll.current) scroll.current.scrollTop = 0;
  }, [query]);
  const start = Math.max(
    0,
    Math.min(events.length - 1, Math.floor(scrollTop / ROW_HEIGHT) - 8),
  );
  const visible = events.slice(
    start,
    start + Math.ceil(listSize.height / ROW_HEIGHT) + 16,
  );
  const tracks = Object.entries(CATEGORIES);

  /** 定位轨道中的活动并停止自动滚动，方便逐条排查 */
  function locate(event: ActivityEvent) {
    setSelected(event);
    setFollow(false);
    const index = events.findIndex((item) => item.id === event.id);
    if (scroll.current)
      scroll.current.scrollTop = Math.max(0, index * ROW_HEIGHT - 80);
  }

  /** 导出当前筛选的完整保留记录，下载失败在日志区域显示 */
  async function exportLogs() {
    setExporting(true);
    setActionError("");
    try {
      await download(
        `/activity/export?${query}`,
        `system-activity-${new Date().toISOString().slice(0, 10)}.jsonl`,
      );
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="activity-workspace" aria-label="系统日志">
      <header className="activity-heading">
        <div className="activity-heading-copy">
          <div className="row">
            <ActivityIcon size={20} />
            <h1>系统日志</h1>
            <span className={`activity-live ${live ? "is-live" : ""}`}>
              {live ? "实时" : "已暂停"}
            </span>
          </div>
        </div>
        <div className="row activity-actions">
          <button
            onClick={() => {
              if (!live) feed.refresh();
              setLive(!live);
            }}
          >
            {live ? <Pause size={15} /> : <Play size={15} />}
            {live ? "暂停" : "继续"}
          </button>
          <button onClick={feed.refresh} aria-label="刷新日志">
            <RefreshCw size={15} />
          </button>
          <button onClick={() => void exportLogs()} disabled={exporting}>
            <Download size={15} />
            {exporting ? "导出中…" : "导出"}
          </button>
          <button
            aria-label="日志设置"
            aria-expanded={settings}
            onClick={() => setSettings(!settings)}
          >
            <Settings2 size={15} />
          </button>
          {settings && (
            <ActivitySettings
              paths={preferences.pollingPaths}
              hideMaintenance={preferences.hideMaintenance}
              onMaintenanceChange={(hideMaintenance) =>
                setPreferences((current) => ({ ...current, hideMaintenance }))
              }
              onClose={() => setSettings(false)}
              onResetLayout={() =>
                setPreferences((current) => ({
                  ...current,
                  overviewHeight: DEFAULT_ACTIVITY_PREFERENCES.overviewHeight,
                  detailWidth: DEFAULT_ACTIVITY_PREFERENCES.detailWidth,
                  detailHeight: DEFAULT_ACTIVITY_PREFERENCES.detailHeight,
                }))
              }
              onSave={(pollingPaths) => {
                setPreferences((current) => ({ ...current, pollingPaths }));
                setSettings(false);
              }}
            />
          )}
        </div>
      </header>
      <div className="activity-filters">
        <div className="activity-search">
          <Search size={16} />
          <input
            aria-label="搜索系统日志"
            placeholder="搜索日志…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <select
          aria-label="日志类型"
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          <option value="">全部类型</option>
          {tracks.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label="日志级别"
          value={level}
          onChange={(event) => setLevel(event.target.value)}
        >
          <option value="">全部级别</option>
          <option value="error">仅错误</option>
          <option value="warning">仅警告</option>
          <option value="info">信息</option>
        </select>
        <label
          className="activity-polling-toggle"
          title="隐藏匹配路径的 GET 200 及普通业务记录；设置自动保存"
        >
          <input
            type="checkbox"
            checked={preferences.hidePolling}
            onChange={(event) =>
              setPreferences((current) => ({
                ...current,
                hidePolling: event.target.checked,
              }))
            }
          />
          隐藏轮询 200
        </label>
        <button
          aria-label="时间筛选"
          aria-expanded={advanced}
          className={since || until ? "active" : ""}
          onClick={() => setAdvanced(!advanced)}
        >
          <SlidersHorizontal size={14} />
        </button>
        {advanced && (
          <div className="activity-time-filters">
            <input
              type="datetime-local"
              aria-label="开始时间"
              value={since}
              onChange={(event) => setSince(event.target.value)}
            />
            <span className="subtle">至</span>
            <input
              type="datetime-local"
              aria-label="结束时间"
              value={until}
              onChange={(event) => setUntil(event.target.value)}
            />
            <button
              onClick={() => {
                setSince("");
                setUntil("");
              }}
            >
              清除时间
            </button>
          </div>
        )}
        {trace && (
          <button
            className="activity-trace-filter"
            onClick={() => setTrace("")}
            title={trace}
          >
            关联请求 {trace.slice(0, 8)} <X size={13} />
          </button>
        )}
      </div>
      <div className="activity-panels" ref={panels}>
        <div
          className="activity-overview"
          aria-label="活动时间轨道"
          style={{ height: overviewHeight }}
        >
          <div className="activity-overview-meta">
            <span>
              轨道 <b>{page?.total.toLocaleString() ?? "—"}</b> 条
            </span>
            <span>
              {events.length
                ? `${new Date(events[0].created_at).toLocaleDateString()} · ${eventTime(events[0].created_at)} — ${eventTime(events.at(-1)!.created_at)}`
                : "等待活动"}
            </span>
          </div>
          {tracks
            .filter(([key]) => !category || key === category)
            .map(([key, label]) => (
              <div className="activity-track" key={key}>
                <button
                  className="activity-track-label"
                  onClick={() => setCategory(category === key ? "" : key)}
                >
                  <span className={`activity-dot cat-${key}`} />
                  {label}
                  <small>{page?.counts[key] ?? 0}</small>
                </button>
                <div className="activity-track-lane">
                  {events
                    .filter((event) => event.category === key)
                    .map((event) => (
                      <button
                        key={event.id}
                        className={`activity-mark cat-${key} ${event.level === "error" ? "has-error" : ""} ${selected?.id === event.id ? "selected" : ""}`}
                        style={{ left: `${eventPosition(event, events)}%` }}
                        title={`${eventTime(event.created_at)} ${event.title}`}
                        aria-label={`定位日志 ${event.id}：${event.title}`}
                        onClick={() => locate(event)}
                      />
                    ))}
                </div>
              </div>
            ))}
        </div>
        <ResizeHandle
          label="轨道高度"
          axis="y"
          value={overviewHeight}
          min={32}
          max={overviewMax}
          onChange={(value) => resize("overviewHeight", value)}
          onReset={() =>
            resize(
              "overviewHeight",
              DEFAULT_ACTIVITY_PREFERENCES.overviewHeight,
            )
          }
        />
        {(feed.error || actionError || !!page?.write_failures) && (
          <div className="activity-error" role="alert">
            {feed.error ||
              actionError ||
              `有 ${page?.write_failures} 条日志写入失败：${page?.last_error}`}
            <button onClick={feed.refresh}>重试</button>
          </div>
        )}
        <div className="activity-list-tools">
          <span>{loadingLabel(feed.loading, events.length)}</span>
          <div className="row">
            {feed.hasOlder && (
              <button
                disabled={feed.olderLoading}
                onClick={() => {
                  setLive(false);
                  setFollow(false);
                  void feed.loadOlder();
                }}
              >
                {feed.olderLoading ? "读取中…" : "加载更早记录"}
              </button>
            )}
            <button
              className={follow ? "active" : ""}
              onClick={() => {
                if (!follow) {
                  feed.refresh();
                  setSelected(null);
                }
                setFollow(!follow);
              }}
            >
              <ArrowDown size={14} />
              {follow ? "跟随最新" : "跳到最新"}
            </button>
          </div>
        </div>
        <div
          ref={body}
          className={`activity-body ${selected ? "with-detail" : ""} ${stacked ? "is-stacked" : ""}`}
        >
          <div
            className="activity-list"
            ref={scroll}
            role="list"
            aria-label="日志时间线"
            onScroll={(event) => {
              const element = event.currentTarget;
              setScrollTop(element.scrollTop);
              if (
                element.scrollHeight -
                  element.scrollTop -
                  element.clientHeight >
                100
              )
                setFollow(false);
            }}
          >
            {!events.length && (
              <div className="activity-empty">
                <ActivityIcon size={32} />
                <strong>
                  {feed.loading ? "正在读取系统活动…" : "暂无匹配的活动"}
                </strong>
              </div>
            )}
            <div style={{ height: start * ROW_HEIGHT }} />
            {visible.map((event) => (
              <button
                role="listitem"
                key={event.id}
                className={`activity-row ${selected?.id === event.id ? "selected" : ""} level-${event.level}`}
                onClick={() => {
                  setSelected(event);
                  setFollow(false);
                }}
                aria-label={`${eventTime(event.created_at)} ${event.title}`}
              >
                <time dateTime={event.created_at}>
                  {eventTime(event.created_at)}
                </time>
                <span className={`activity-badge cat-${event.category}`}>
                  {CATEGORIES[event.category as keyof typeof CATEGORIES] ??
                    event.category}
                </span>
                <span className="activity-event-kind">{event.event}</span>
                <span className="activity-row-title">{event.title}</span>
                {event.level !== "info" && (
                  <span className="activity-level">
                    {event.level === "error" ? "错误" : "警告"}
                  </span>
                )}
                <span className="activity-duration">
                  {event.duration_ms === null
                    ? ""
                    : `${Math.round(event.duration_ms)} ms`}
                </span>
              </button>
            ))}
            <div
              style={{
                height:
                  Math.max(0, events.length - start - visible.length) *
                  ROW_HEIGHT,
              }}
            />
          </div>
          {selected && (
            <>
              <ResizeHandle
                label={stacked ? "详情高度" : "详情宽度"}
                axis={stacked ? "y" : "x"}
                reverse
                value={detailSize}
                min={stacked ? 80 : 260}
                max={detailMax}
                onChange={(value) =>
                  resize(stacked ? "detailHeight" : "detailWidth", value)
                }
                onReset={() =>
                  resize(
                    stacked ? "detailHeight" : "detailWidth",
                    stacked
                      ? DEFAULT_ACTIVITY_PREFERENCES.detailHeight
                      : DEFAULT_ACTIVITY_PREFERENCES.detailWidth,
                  )
                }
              />
              <div
                className="activity-detail-panel"
                style={{ flexBasis: detailSize }}
              >
                <ActivityDetail
                  event={selected}
                  onClose={() => setSelected(null)}
                  onTrace={(value) => {
                    setCategory("");
                    setLevel("");
                    setSearch("");
                    setKeyword("");
                    setSince("");
                    setUntil("");
                    setTrace(value);
                    setFollow(false);
                  }}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

/** 显示列表当前加载状态，避免把筛选总数误认为已渲染条数 */
function loadingLabel(loading: boolean, count: number) {
  return loading ? "读取中…" : `${count.toLocaleString()} 条已载入`;
}

/** 按需读取选中事件详情并展示请求、消息、工具结果及关联信息 */
function ActivityDetail({
  event,
  onClose,
  onTrace,
}: {
  event: ActivityEvent;
  onClose: () => void;
  onTrace: (trace: string) => void;
}) {
  const [detail, setDetail] = useState<ActivityEvent | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError("");
    setCopied(false);
    void api<ActivityEvent>(
      `/activity/${event.id}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setDetail(value);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [event.id]);
  /** 复制已遮盖的日志详情，浏览器拒绝剪贴板时显示原因 */
  async function copyDetail() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(detail, null, 2));
      setCopied(true);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  return (
    <aside className="activity-detail" aria-label="日志详情">
      <header>
        <strong>事件 #{event.id}</strong>
        <div className="row">
          <button disabled={!detail} onClick={() => void copyDetail()}>
            {copied ? "已复制" : "复制 JSON"}
          </button>
          <button aria-label="关闭日志详情" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
      </header>
      <div className="activity-detail-scroll">
        <h2>{event.title}</h2>
        <dl>
          <dt>时间</dt>
          <dd>
            {new Date(event.created_at).toLocaleString()} · {event.created_at}
          </dd>
          <dt>来源</dt>
          <dd>
            {event.source} / {event.event}
          </dd>
          <dt>级别 / 耗时</dt>
          <dd>
            {event.level} /{" "}
            {event.duration_ms === null ? "—" : `${event.duration_ms} ms`}
          </dd>
          {event.trace_id && (
            <>
              <dt>关联请求</dt>
              <dd>
                <button
                  className="text-button"
                  onClick={() => onTrace(event.trace_id)}
                  title="筛选同一请求及其后台任务"
                >
                  {event.trace_id}
                </button>
              </dd>
            </>
          )}
          {event.job_id && (
            <>
              <dt>任务</dt>
              <dd>{event.job_id}</dd>
            </>
          )}
          {event.conversation_id && (
            <>
              <dt>会话</dt>
              <dd>{event.conversation_id}</dd>
            </>
          )}
          {event.project_id && (
            <>
              <dt>项目</dt>
              <dd>{event.project_id}</dd>
            </>
          )}
        </dl>
        <h3>完整记录</h3>
        {error && (
          <p role="alert" className="activity-error">
            {error}
          </p>
        )}
        {!detail && !error ? (
          <p className="subtle">正在读取详情…</p>
        ) : (
          <pre>{JSON.stringify(detail?.payload, null, 2)}</pre>
        )}
      </div>
    </aside>
  );
}
