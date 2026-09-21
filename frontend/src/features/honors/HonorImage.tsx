import { useEffect, useRef, useState } from "react";
import { ImageOff } from "lucide-react";
import { request } from "../../shared/lib/api";

/** 按可见区域延迟读取受保护的证书分页，切换页面后回收图片地址 */
export default function HonorImage({
  id,
  page = 1,
  name,
}: {
  id: string;
  page?: number;
  name: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(
    /* 当前证书进入视口时下载缩略图以免一次读取整个荣誉库 */ () => {
      const controller = new AbortController();
      let objectUrl = "";
      setUrl("");
      setError("");
      /** 只发布属于本次证书和页码的响应 */
      async function read() {
        try {
          const response = await request(`/honors/${id}/pages/${page}`, {
            signal: controller.signal,
          });
          const blob = await response.blob();
          if (controller.signal.aborted) return;
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        } catch (reason) {
          if (!controller.signal.aborted) setError((reason as Error).message);
        }
      }
      const observer = new IntersectionObserver(
        /* 可见后只读取一次，后续交给浏览器展示 */ (entries) => {
          if (
            entries.some(
              /* 检查图片容器是否可见 */ (entry) => entry.isIntersecting,
            )
          ) {
            observer.disconnect();
            void read();
          }
        },
      );
      if (container.current) observer.observe(container.current);
      return /* 释放观察器、请求及当前对象地址 */ () => {
        observer.disconnect();
        controller.abort();
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      };
    },
    [id, page],
  );
  return (
    <div ref={container} className="honor-image">
      {url ? (
        <img src={url} alt={`${name}，第 ${page} 页`} />
      ) : (
        <span className="subtle">
          {error ? (
            <>
              <ImageOff size={22} />
              {error}
            </>
          ) : (
            "载入证书…"
          )}
        </span>
      )}
    </div>
  );
}
