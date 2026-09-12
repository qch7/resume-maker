const token =
  document.querySelector<HTMLMetaElement>('meta[name="resume-token"]')
    ?.content ?? "";

export class ApiError extends Error {
  /** 保留 HTTP 状态码，使调用方能区分冲突、鉴权和普通请求错误。 */
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

/** 附加实例令牌发送同源请求，并将失败响应转换为统一 API 异常。 */
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
  });
  if (!response.ok) {
    const body = await response.json().catch(
      /* 保留可展示的失败原因，并避免已取消请求更新页面。 */ () => ({
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

/** 序列化 JSON 请求并解码响应，同时允许调用方传入取消信号。 */
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

/** 下载受令牌保护的文件，触发浏览器保存并及时回收对象 URL。 */
export async function download(path: string, filename: string, method = "GET") {
  const response = await request(path, { method });
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(
    /* 下载触发后释放临时文件 URL。 */ () => URL.revokeObjectURL(url),
    1000,
  );
}
