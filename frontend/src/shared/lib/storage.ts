/** 读取本地 JSON 缓存；遇到禁用存储或损坏内容时使用默认值 */
export function loadLocal<T>(key: string, fallback: T): T {
  try {
    const stored = localStorage.getItem(key);
    return stored ? (JSON.parse(stored) as T) : fallback;
  } catch {
    return fallback;
  }
}
