import type { ImportTrace } from "../types/imports";

/** 按需展示原件采用的处理方式，处理器停用后仍能核对历史来源 */
export default function ImportDetails({
  trace,
}: {
  trace?: ImportTrace | null;
}) {
  if (!trace) return null;
  return (
    <details className="import-details">
      <summary>文件处理记录</summary>
      <p>
        {trace.id} · {trace.version}
      </p>
      <p>
        原始格式：{trace.format}
        {trace.pages ? ` · ${trace.pages} 页` : ""}
      </p>
      <p>
        原件校验值：<code>{trace.source_sha256}</code>
      </p>
    </details>
  );
}
