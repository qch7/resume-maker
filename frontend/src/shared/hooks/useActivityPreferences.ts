import { useSyncExternalStore, type SetStateAction } from "react";
import { loadLocal, storage } from "../lib/storage";
import { api } from "../lib/api";
import {
  restoreActivityPreferences,
  type ActivityPreferences,
  type SavedActivityPreferences,
} from "../lib/activityPreferences";

const listeners = new Set<() => void>();
let defaultRules = "";
let snapshot: { preferences: ActivityPreferences; error: string } | undefined;

/** 首次挂载时读取已恢复的存储，设置页和插件页面共享同一快照 */
function current() {
  snapshot ??= {
    preferences: restoreActivityPreferences(
      loadLocal<SavedActivityPreferences | null>("rm.activity", null),
      defaultRules,
    ),
    error: "",
  };
  return snapshot;
}

/** 挂载工作台前读取后端有效规则，配置变化无需重新构建前端 */
export async function initializeActivityPreferences() {
  const defaults = await api<{ hidden_rules: string[] }>("/activity/defaults");
  defaultRules = defaults.hidden_rules.join("\n");
  snapshot = undefined;
  current();
}

/** 订阅公开设置变化，插件卸载时由 React 撤销自己的订阅 */
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 原子更新显示偏好并持久化，多个页面不会用各自旧状态覆盖设置 */
function setPreferences(value: SetStateAction<ActivityPreferences>) {
  const previous = current();
  const preferences =
    typeof value === "function" ? value(previous.preferences) : value;
  let error = "";
  try {
    const { hiddenRules, ...saved } = preferences;
    storage.setItem(
      "rm.activity",
      JSON.stringify({
        ...saved,
        rulesOverride: hiddenRules === defaultRules ? undefined : hiddenRules,
      }),
    );
  } catch {
    error = "无法保存日志显示设置";
  }
  snapshot = { preferences, error };
  for (const listener of listeners) listener();
}

/** 在系统设置及独立日志页面同步偏好，不依赖可选插件实现 */
export function useActivityPreferences() {
  return {
    ...useSyncExternalStore(subscribe, current),
    defaultRules,
    setPreferences,
  };
}
