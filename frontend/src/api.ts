const token =
  document.querySelector<HTMLMetaElement>('meta[name="resume-token"]')
    ?.content ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

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
    const body = await response
      .json()
      .catch(() => ({ detail: `请求失败 (${response.status})` }));
    const message =
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail);
    throw new ApiError(message, response.status);
  }
  return response;
}

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

export async function download(path: string, filename: string, method = "GET") {
  const response = await request(path, { method });
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function loadLocal<T>(key: string, fallback: T): T {
  try {
    const stored = localStorage.getItem(key);
    return stored ? (JSON.parse(stored) as T) : fallback;
  } catch {
    return fallback;
  }
}
