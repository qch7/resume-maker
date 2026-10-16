import { storage } from "@resume-maker/plugin-sdk/shared/lib/storage";

/** 导航偏好按当前资料目录、本页隔离，避免多窗口争用业务草稿版本 */
export function readWorkspaceSession<T>(key: string, fallback: T): T {
  try {
    const value = sessionStorage.getItem(
      `rm.workspace.${storage.namespace()}.${key}`,
    );
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

/** 页面位置只存会话偏好，浏览器禁用存储时仍保留地址及业务草稿 */
export function saveWorkspaceSession(key: string, value: unknown) {
  try {
    sessionStorage.setItem(
      `rm.workspace.${storage.namespace()}.${key}`,
      JSON.stringify(value),
    );
  } catch {
    // 位置缓存失败不阻止项目、简历草稿保存
  }
}
