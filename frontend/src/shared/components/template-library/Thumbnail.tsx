import { FileImage, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { request } from "../../lib/api";

/** 进入可见范围后获取真实首屏；切换分类或关闭弹窗时中止下载并释放图片 */
export default function Thumbnail({ id, name }: { id: string; name: string }) {
  const element = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(
    /* 避免一次性为屏幕外的整个模板库启动排版 */ () => {
      const observer = new IntersectionObserver(
        /* 预加载即将滚入视口的卡片 */ (entries) => {
          if (
            entries.some(
              /* 只需有一个可见观察对象 */ (entry) => entry.isIntersecting,
            )
          ) {
            setVisible(true);
            observer.disconnect();
          }
        },
        { rootMargin: "120px" },
      );
      if (element.current) observer.observe(element.current);
      return /* 卸载时清理可见性观察 */ () => observer.disconnect();
    },
    [],
  );
  useEffect(
    /* 模板切换时隔离迟到响应；失败可显式重试 */ () => {
      if (!visible) return;
      const controller = new AbortController();
      let objectUrl = "";
      setUrl("");
      setError("");
      /** 通过实例令牌读取模板图片且不执行模板中的外部资源 */
      async function read() {
        try {
          const response = await request(
            `/template-library/items/${encodeURIComponent(id)}/thumbnail`,
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
      return /* 取消旧请求并回收对象地址 */ () => {
        controller.abort();
        if (objectUrl) URL.revokeObjectURL(objectUrl);
      };
    },
    [id, visible, attempt],
  );
  return (
    <div className="library-thumbnail" ref={element}>
      {url ? (
        <img src={url} alt={`${name}的模板首页预览`} />
      ) : (
        <div className="library-thumbnail-status">
          <FileImage size={28} strokeWidth={1.3} />
          <span>{error ? "预览暂不可用" : "正在载入预览…"}</span>
          {error && (
            <>
              <small title={error}>{error}</small>
              <button
                onClick={
                  /* 重试不选中或应用当前模板 */ (event) => {
                    event.stopPropagation();
                    setAttempt(attempt + 1);
                  }
                }
              >
                <RotateCw size={13} />
                重试预览
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
