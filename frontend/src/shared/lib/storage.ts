import { api } from "./api";
import { registerDraft } from "./draftRegistry";
import { capabilities } from "./capabilities";
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
  generation: () => capabilities().generation,
  changed: () => {
    statusVersion++;
    for (const listener of listeners) listener();
  },
});
registerDraft("workspace-storage", storage.flush, true);

/** 从当前资料目录恢复草稿并初始化保存队列 */
export async function initializeStorage() {
  await storage.initialize();
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
