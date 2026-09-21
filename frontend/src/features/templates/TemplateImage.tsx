import { useEffect, useState } from "react";
import { request } from "../../shared/lib/api";

/** 显示模板内嵌图片并回收临时下载地址 */
export default function TemplateImage({
  taskId,
  nodeId,
}: {
  taskId: string;
  nodeId: string;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(
    /* 只读取当前任务内嵌图片，位置变动后忽略旧响应 */ () => {
      const controller = new AbortController();
      let objectUrl = "";
      setUrl("");
      setError("");
      /** 下载模板内嵌图片并在组件有效时显示 */
      async function read() {
        try {
          const response = await request(
            `/templates/analyses/${taskId}/images/${nodeId}`,
            { signal: controller.signal },
          );
          const blob = await response.blob();
          if (controller.signal.aborted) return;
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        } catch (reason) {
          if (!controller.signal.aborted) setError((reason as Error).message);
        }
      }
      void read();
      return /* 取消加载并回收本次预览资源 */ () => {
        controller.abort();
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      };
    },
    [taskId, nodeId],
  );
  return url ? (
    <img className="template-image" src={url} alt="模板原图，待核对用途" />
  ) : (
    <span className="subtle">{error || "正在载入原图…"}</span>
  );
}
