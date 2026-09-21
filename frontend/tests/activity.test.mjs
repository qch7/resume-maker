import assert from "node:assert/strict";
import test from "node:test";
import { eventPosition, mergeEvents } from "../src/features/activity/model.ts";
import {
  DEFAULT_ACTIVITY_PREFERENCES,
  pollingPathError,
  restoreActivityPreferences,
} from "../src/features/activity/preferences.ts";

/** 构造最小日志摘要，测试只关注列表游标和时间定位 */
function event(id, created_at = "2026-09-21T01:00:00Z") {
  return { id, created_at, title: `event-${id}` };
}

test("增量批次去重并按持久游标排序", () => {
  assert.deepEqual(
    mergeEvents([event(2), event(3)], [event(3), event(1), event(4)]).map(
      (item) => item.id,
    ),
    [1, 2, 3, 4],
  );
});

test("实时跟随保留最新窗口，读取历史保留较早窗口", () => {
  const values = Array.from({ length: 3100 }, (_, index) => event(index + 1));
  assert.equal(mergeEvents([], values).length, 3000);
  assert.equal(mergeEvents([], values)[0].id, 101);
  assert.equal(mergeEvents([], values, true).at(-1).id, 3000);
});

test("活动轨道按真实时间定位且处理同毫秒事件", () => {
  const events = [
    event(1, "2026-09-21T01:00:00Z"),
    event(2, "2026-09-21T01:00:05Z"),
    event(3, "2026-09-21T01:00:10Z"),
  ];
  assert.equal(eventPosition(events[0], events), 0);
  assert.equal(eventPosition(events[1], events), 49.75);
  assert.equal(eventPosition(events[2], events), 99.5);
  assert.equal(eventPosition(event(1), [event(1)]), 50);
});

test("成功轮询响应撤回缓存中的请求，保留警告和工具消息", () => {
  const values = [
    { ...event(1), category: "api", level: "info", trace_id: "poll" },
    { ...event(2), category: "service", level: "info", trace_id: "poll" },
    { ...event(3), category: "service", level: "warning", trace_id: "poll" },
    { ...event(4), category: "tool", level: "info", trace_id: "poll" },
    { ...event(5), category: "api", level: "info", trace_id: "other" },
  ];
  assert.deepEqual(
    mergeEvents(values, [], false, ["poll"]).map((item) => item.id),
    [3, 4, 5],
  );
});

test("默认过滤开启，保存的开关、规则和面板尺寸可恢复", () => {
  assert.deepEqual(
    restoreActivityPreferences(null),
    DEFAULT_ACTIVITY_PREFERENCES,
  );
  const saved = {
    hidePolling: false,
    pollingPaths: "/api/custom/*",
    overviewHeight: 70,
    detailWidth: 520,
    detailHeight: 320,
  };
  assert.deepEqual(
    restoreActivityPreferences(JSON.parse(JSON.stringify(saved))),
    saved,
  );
  const broken = restoreActivityPreferences({
    hidePolling: "false",
    pollingPaths: 42,
    overviewHeight: NaN,
    detailWidth: -200,
  });
  assert.equal(broken.hidePolling, true);
  assert.equal(broken.overviewHeight, 160);
  assert.equal(broken.detailWidth, 32);
  assert.equal(pollingPathError("/api/state\n/api/custom/*"), "");
  assert.equal(pollingPathError(""), "");
  assert.ok(pollingPathError("/api/state?query=1"));
  assert.ok(pollingPathError("state"));
});
