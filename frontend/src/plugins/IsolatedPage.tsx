import { useEffect, useRef } from "react";
import { api } from "../shared/lib/api";

/** 隔离界面只能通过独立消息端口调用本插件声明的操作 */
export function IsolatedPage({
  id,
  entry,
  generation,
}: {
  id: string;
  entry: string;
  generation: number;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const parts = new URL(entry, location.origin).pathname.split("/");
  const source = `/plugin-ui/${encodeURIComponent(id)}/${parts[3]}`;
  useEffect(() => {
    const iframe = frame.current;
    if (!iframe) return;
    let channel: MessageChannel | undefined;
    let disposed = false;
    let active = 0;
    /** 每次 iframe 导航都撤销旧端口，回复固定到原会话 */
    function connect() {
      channel?.port1.close();
      channel = new MessageChannel();
      const port = channel.port1;
      port.onmessage = async ({ data }: MessageEvent<unknown>) => {
        if (disposed || !data || typeof data !== "object") return;
        const value = data as Record<string, unknown>;
        if (
          !Number.isSafeInteger(value.id) ||
          typeof value.method !== "string" ||
          !/^[a-zA-Z][a-zA-Z0-9_.-]{0,100}$/.test(value.method)
        )
          return;
        let length: number;
        try {
          length = JSON.stringify(data).length;
        } catch {
          port.postMessage({
            id: value.id,
            ok: false,
            error: "请求须为 JSON 数据",
          });
          return;
        }
        if (length > 2 * 1024 * 1024 || active >= 16) {
          port.postMessage({
            id: value.id,
            ok: false,
            error: "请求超过插件桥限制",
          });
          return;
        }
        active++;
        try {
          const result = await api(
            `/plugins/rpc/${encodeURIComponent(id)}/${value.method}`,
            "POST",
            { payload: value.payload, generation },
          );
          if (!disposed && channel?.port1 === port)
            port.postMessage({ id: value.id, ok: true, result });
        } catch (error) {
          if (!disposed && channel?.port1 === port)
            port.postMessage({
              id: value.id,
              ok: false,
              error: error instanceof Error ? error.message : "插件操作失败",
            });
        } finally {
          active--;
        }
      };
      iframe?.contentWindow?.postMessage(
        { type: "resume-plugin-connect", id, generation },
        "*",
        [channel.port2],
      );
    }
    iframe.addEventListener("load", connect);
    iframe.src = source;
    return () => {
      disposed = true;
      iframe.removeEventListener("load", connect);
      channel?.port1.postMessage({ type: "dispose" });
      channel?.port1.close();
    };
  }, [id, generation, source]);
  return (
    <iframe
      ref={frame}
      sandbox="allow-scripts"
      title={id}
      className="plugin-isolated-page"
    />
  );
}
