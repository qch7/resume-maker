import { useEffect, useState } from "react";
import { request } from "../../shared/lib/api";
/** 加载受鉴权保护的实际分页图片，在卸载时回收浏览器对象 URL */
export default function PrintedPage({
  exportId,
  path,
  page,
}: { page: number } & (
  | { exportId: string; path?: never }
  | { path: string; exportId?: never }
)) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const imagePath = path ?? `/exports/${exportId}/page-${page}.png`;
  useEffect(() => {
    setUrl("");
    setError("");
    let objectUrl = "",
      stopped = false;
    void request(imagePath)
      .then(/* 将下载响应转换为浏览器可展示的文件内容 */ (r) => r.blob())
      .then(
        /* 将下载响应转换为浏览器可展示的文件内容 */ (blob) => {
          if (!stopped) {
            objectUrl = URL.createObjectURL(blob);
            setUrl(objectUrl);
          }
        },
      )
      .catch(
        /* 取消后忽略迟到的错误 */ (e) => {
          if (!stopped) setError(e.message);
        },
      );
    return () => {
      stopped = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imagePath]);
  return url ? (
    <img
      className="printed-page"
      src={url}
      alt={`Word 实际渲染第 ${page} 页`}
    />
  ) : (
    <p className="subtle">{error || `载入第 ${page} 页…`}</p>
  );
}
