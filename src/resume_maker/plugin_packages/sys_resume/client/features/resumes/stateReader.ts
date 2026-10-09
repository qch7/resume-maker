/** 每个工作台独立保存聚合版本，迟到请求不能改写缓存 */
export function createStateReader<T>(
  execute: (version: string | null, signal?: AbortSignal) => Promise<Response>,
) {
  let version: string | null = null;
  let value: T | undefined;
  let serial = 0;
  return async (signal?: AbortSignal): Promise<T> => {
    const current = ++serial;
    const response = await execute(version, signal);
    if (response.status === 304) {
      if (value === undefined)
        throw new Error("工作台版本已失效，请重新加载。");
      return value;
    }
    const result = (await response.json()) as T;
    if (current === serial && !signal?.aborted) {
      version = response.headers.get("etag");
      value = result;
    }
    return result;
  };
}
