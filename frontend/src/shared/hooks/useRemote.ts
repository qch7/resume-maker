import { useEffect, useState } from "react";
import { api } from "../lib/api";
/** 读取远端数据，以路径和刷新序号隔离响应并在切换时取消旧请求 */
export function useRemote<T>(path: string | null, refresh: number) {
  const [result, setResult] = useState<{
    path: string;
    refresh: number;
    value: T;
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setError("");
    void api<T>(path, "GET", undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setResult({ path, refresh, value });
      })
      .catch(
        /* 取消后忽略迟到的错误 */ (e) => {
          if (!controller.signal.aborted) setError(e.message);
        },
      );
    return () => controller.abort();
  }, [path, refresh]);
  return {
    data: result?.path === path ? result.value : null,
    ready: result?.path === path && result.refresh === refresh,
    error,
  };
}
