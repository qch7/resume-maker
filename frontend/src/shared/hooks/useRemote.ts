import { useEffect, useState } from "react";
import { api } from "../lib/api";
/** 读取远端数据，以路径和刷新序号隔离响应，并在切换时取消旧请求。 */
export function useRemote<T>(path: string | null, refresh: number) {
  const [result, setResult] = useState<{
    path: string;
    refresh: number;
    value: T;
  } | null>(null);
  const [error, setError] = useState("");
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (!path) return;
      const controller = new AbortController();
      setError("");
      void api<T>(path, "GET", undefined, controller.signal)
        .then(
          /* 在异步操作成功后同步结果及相关状态。 */ (value) => {
            if (!controller.signal.aborted) setResult({ path, refresh, value });
          },
        )
        .catch(
          /* 保留可展示的失败原因，并避免已取消请求更新页面。 */ (e) => {
            if (!controller.signal.aborted) setError(e.message);
          },
        );
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        controller.abort();
    },
    [path, refresh],
  );
  return {
    data: result?.path === path ? result.value : null,
    ready: result?.path === path && result.refresh === refresh,
    error,
  };
}
