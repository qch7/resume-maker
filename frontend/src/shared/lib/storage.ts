import { api } from "./api";
import { registerDraft } from "./draftRegistry";
import {
  createPersistence,
  type StorageSnapshot,
  type StoredValue,
} from "./persistence";

const listeners = new Set<() => void>();
let statusVersion = 0;
export const storage = createPersistence({
  read: () => api<StorageSnapshot>("/workspace-storage"),
  write: (key, value) =>
    api<StoredValue>(
      `/workspace-storage/${encodeURIComponent(key)}`,
      "PUT",
      value,
    ),
  local: {
    getItem: (key) => localStorage.getItem(key),
    setItem: (key, value) => localStorage.setItem(key, value),
    removeItem: (key) => localStorage.removeItem(key),
    keys: () => Object.keys(localStorage),
  },
  client: crypto.randomUUID(),
  changed: () => {
    statusVersion++;
    for (const listener of listeners) listener();
  },
});
registerDraft("workspace-storage", storage.flush, true);

/** 首次升级把浏览器旧草稿导入当前目录，恢复备份后不重放其他代次旧内容 */
export async function initializeStorage() {
  await storage.initialize();
  try {
    const namespace = storage.namespace();
    const owner = localStorage.getItem("rm.legacy.owner");
    if (owner && owner !== namespace) return;
    if (localStorage.getItem(`rm.legacy.done.${namespace}`)) return;
    localStorage.setItem("rm.legacy.owner", namespace);
    const keys = Object.keys(localStorage).filter((key) =>
      /^rm\.(resume\.v2\.|field\.|chat\.|profile\.|theme$|layout$|sidebarSort$|activity$|template\.library\.view$)/.test(
        key,
      ),
    );
    for (const key of keys) {
      const value = localStorage.getItem(key);
      if (value !== null && !storage.has(key)) storage.setItem(key, value);
    }
    await storage.flush();
    localStorage.setItem(`rm.legacy.done.${namespace}`, "1");
  } catch {
    // 原浏览器记录始终保留，保存失败由统一状态提示处理
  }
}

/** 通知保存提示更新，不把输入正文放到公共状态中 */
export function subscribeStorage(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
/** 返回稳定的通知版本，供 React 订阅外部保存队列 */
export const storageVersion = () => statusVersion;

/** 读取已恢复的本机草稿，损坏内容使用默认值 */
export function loadLocal<T>(key: string, fallback: T): T {
  try {
    const stored = storage.getItem(key);
    return stored ? (JSON.parse(stored) as T) : fallback;
  } catch {
    return fallback;
  }
}
