import { useEffect, useState } from "react";
import { request } from "../../shared/lib/api";
/** 按导出标识加载实际分页图片，在卸载时回收浏览器对象 URL。 */
export default function PrintedPage({
  exportId,
  page,
}: {
  exportId: string;
  page: number;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      let objectUrl = "",
        stopped = false;
      void request(`/exports/${exportId}/page-${page}.png`)
        .then(/* 将下载响应转换为浏览器可展示的文件内容。 */ (r) => r.blob())
        .then(
          /* 将下载响应转换为浏览器可展示的文件内容。 */ (blob) => {
            if (!stopped) {
              objectUrl = URL.createObjectURL(blob);
              setUrl(objectUrl);
            }
          },
        )
        .catch(
          /* 保留可展示的失败原因，并避免已取消请求更新页面。 */ (e) => {
            if (!stopped) setError(e.message);
          },
        );
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () => {
        stopped = true;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      };
    },
    [exportId, page],
  );
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
