const token =
  document.querySelector<HTMLMetaElement>('meta[name="resume-token"]')
    ?.content ?? "";

export class ApiError extends Error {
  /** 保留 HTTP 状态码供调用方判断错误类型 */
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

/** 上报浏览器错误，使用独立请求避免日志接口失败后递归记录 */
export function reportClientError(event: string, failure: unknown, path = "") {
  const error = failure instanceof Error ? failure : new Error(String(failure));
  void fetch("/api/activity/client", {
    method: "POST",
    headers: { "x-resume-token": token, "content-type": "application/json" },
    body: JSON.stringify({
      event,
      message: error.message.slice(0, 2000),
      stack: (error.stack ?? "").slice(0, 12000),
      path: path.slice(0, 2000),
    }),
  }).catch(() => undefined);
}

/** 携带实例令牌发送同源请求并将失败响应转为 API 异常 */
export async function request(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "x-resume-token": token,
      ...(options.body ? { "content-type": "application/json" } : {}),
      ...options.headers,
    },
  }).catch((error: Error) => {
    if (!path.startsWith("/activity") && !options.signal?.aborted)
      reportClientError("network_error", error, path);
    throw error;
  });
  if (!response.ok) {
    const body = await response.json().catch(
      /* 取消后忽略迟到的错误 */ () => ({
        detail: `请求失败 (${response.status})`,
      }),
    );
    const message =
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail);
    throw new ApiError(message, response.status);
  }
  return response;
}

/** 序列化 JSON 请求并解码响应，同时允许调用方传入取消信号 */
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await request(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  return response.json() as Promise<T>;
}

/** 下载受令牌保护的文件，触发浏览器保存并及时回收对象 URL */
export async function download(path: string, filename: string, method = "GET") {
  const response = await request(path, { method });
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(
    /* 下载触发后释放临时文件 URL */ () => URL.revokeObjectURL(url),
    1000,
  );
}
