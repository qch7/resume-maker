import { useEffect, useState } from "react";
import { api } from "@resume-maker/plugin-sdk/shared/lib/api";

interface Download {
  id: string;
  url: string;
  state: string;
  received: number;
  total: number | null;
  path: string | null;
  message?: string;
}
const labels: Record<string, string> = {
  downloading: "下载中",
  cancelling: "正在取消",
  cancelled: "已取消",
  ready: "摘要已核验",
  failed: "下载失败",
  interrupted: "下载中断",
};

/** 显式提供地址和摘要，下载结束后交回原有包检查入口 */
export default function PackageDownloads({
  onChoose,
}: {
  onChoose: (path: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [digest, setDigest] = useState("");
  const [downloads, setDownloads] = useState<Download[]>([]);
  const [error, setError] = useState("");
  const [request, setRequest] = useState<{
    id: string;
    url: string;
    sha256: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    let running = false;
    /** 只读取持久进度，关闭窗口不会取消后台下载 */
    async function refresh() {
      if (running) return;
      running = true;
      try {
        const rows = await api<Download[]>("/plugins/downloads");
        if (live) setDownloads(rows);
      } catch {
        /* 服务重启期间保留最后一次已知进度 */
      } finally {
        running = false;
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 1000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  /** 重发相同身份可恢复丢失的开始响应，来源变化才创建新身份 */
  async function start() {
    setBusy(true);
    setError("");
    const body =
      request?.url === url && request.sha256 === digest
        ? request
        : { id: crypto.randomUUID(), url, sha256: digest };
    setRequest(body);
    try {
      const row = await api<Download>("/plugins/downloads", "POST", body);
      setDownloads((values) => [
        ...values.filter((value) => value.id !== row.id),
        row,
      ]);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 取消只发送意图，界面等待服务确认实际结束 */
  async function cancel(id: string) {
    try {
      const row = await api<Download>(
        `/plugins/downloads/${id}/cancel`,
        "POST",
      );
      setDownloads((values) =>
        values.map((value) => (value.id === id ? row : value)),
      );
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  return (
    <details>
      <summary>从明确地址下载插件</summary>
      <p>
        填写发布者提供的 HTTPS 地址和 SHA-256
        文件摘要。下载完成后仍需检查插件权限。
      </p>
      <input
        aria-label="插件下载地址"
        value={url}
        onChange={(event) => {
          setUrl(event.target.value);
          setRequest(null);
        }}
        placeholder="https://…/plugin.rmp"
      />
      <input
        aria-label="插件文件摘要"
        value={digest}
        onChange={(event) => {
          setDigest(event.target.value.trim());
          setRequest(null);
        }}
        placeholder="64 位 SHA-256"
      />
      <button
        disabled={busy || !url || !/^[a-f0-9]{64}$/.test(digest)}
        onClick={() => void start()}
      >
        下载或查询本次请求
      </button>
      {error && <p role="alert">{error}</p>}
      {downloads.map((row) => (
        <div key={row.id}>
          <p>
            {labels[row.state] ?? row.state} · {row.received.toLocaleString()} /{" "}
            {row.total?.toLocaleString() ?? "未知"} 字节
          </p>
          <small>{row.url}</small>
          {row.message && <p>{row.message}</p>}
          {row.state === "downloading" && (
            <button onClick={() => void cancel(row.id)}>取消下载</button>
          )}
          {row.state === "ready" && row.path && (
            <button onClick={() => onChoose(row.path!)}>检查此插件包</button>
          )}
        </div>
      ))}
    </details>
  );
}
