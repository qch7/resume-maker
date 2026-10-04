export interface ClientDescriptor {
  id: string;
  entry: { mode: string; entry: string };
  provides?: Record<string, { version: string; cardinality: "one" | "many" }>;
  bindings?: Record<
    "client" | "remote",
    Record<string, { owners: string[]; many: boolean }>
  >;
}

export interface Capabilities {
  generation: number;
  host_api: string;
  client_api: string;
  ready: boolean;
  plugins: string[];
  services: string[];
  sandbox: Record<string, boolean>;
  client: ClientDescriptor[];
}

let current: Capabilities | null = null;

/** 启动协商成功后固定当前窗口的配置代次 */
export function setCapabilities(value: Capabilities) {
  if (
    !Number.isSafeInteger(value.generation) ||
    value.generation < 1 ||
    value.client_api !== "1.0.0" ||
    !Array.isArray(value.plugins) ||
    !Array.isArray(value.services) ||
    !Array.isArray(value.client) ||
    !value.ready
  )
    throw new Error("工作台能力清单无效或系统尚未就绪。");
  current = value;
}

/** 读取固定代次，不自动把旧窗口输入升级到另一套插件配置 */
export function capabilities() {
  if (!current) throw new Error("工作台尚未完成能力协商。");
  return current;
}

/** 所有界面入口共用后端确认的能力状态 */
export function hasPlugin(identifier: string) {
  return current?.plugins.includes(identifier) ?? false;
}

/** 未协商时仅发送启动读取，协商后的写入携带配置代次 */
export function generationHeaders(): Record<string, string> {
  return current ? { "x-resume-generation": String(current.generation) } : {};
}
