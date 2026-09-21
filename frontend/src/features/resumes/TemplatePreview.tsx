import { useEffect, useRef, useState } from "react";
import { api, download } from "../../shared/lib/api";
import PrintedPage from "./PrintedPage";
import { createPreviewQueue, type PreviewState } from "./templatePreviewQueue";

interface PreviewResult {
  id: string;
  pages: number | null;
  render_error: string | null;
}

/** 使用正式导出填充器展示所选模板，自动排版不保存组合或发布经历 */
export default function TemplatePreview({
  input,
  templateId,
  zoom,
  hidden,
  run,
}: {
  input: string | null;
  templateId: string | null;
  zoom: number;
  hidden: boolean;
  run: (work: () => Promise<void>) => void;
}) {
  const [state, setState] = useState<PreviewState<PreviewResult>>({
    key: null,
    status: "idle",
  });
  const queue = useRef<ReturnType<
    typeof createPreviewQueue<PreviewResult>
  > | null>(null);
  useEffect(
    /* 队列跨资料及模板切换保留以防重复启动 Word */ () => {
      const current = createPreviewQueue(
        /* 发送临时预览快照 */ (key, signal) =>
          api<PreviewResult>(
            "/resume-previews",
            "POST",
            JSON.parse(key),
            signal,
          ),
        setState,
      );
      queue.current = current;
      return /* 卸载时回收防抖计时器并拒绝迟到响应 */ () => {
        current.dispose();
        queue.current = null;
      };
    },
    [],
  );
  useEffect(
    /* 队列合并连续输入并等待当前渲染完成 */ () => {
      queue.current?.submit(input);
    },
    [input],
  );

  const current = state.key === input;
  const previousTemplate = state.result
    ? (JSON.parse(state.result.key) as { template_id: string | null })
        .template_id
    : null;
  const result =
    previousTemplate === templateId ? state.result?.value : undefined;
  const complete = current && state.status === "ready";
  const error = current
    ? state.error || (complete ? result?.render_error : "")
    : "";
  const updated = complete && !!result?.pages;
  const status = !input
    ? "正在读取经历版本…"
    : error
      ? "当前资料预览未完成"
      : current && state.status === "rendering"
        ? "正在更新预览…"
        : "资料已变化，稍后自动更新预览…";

  return (
    <div className="template-live-preview" hidden={hidden}>
      {!updated && (
        <div
          className="template-preview-status"
          role="status"
          aria-live="polite"
        >
          <span>{status}</span>
          {error && <p className="warning">{error}</p>}
          {result?.pages && !updated && (
            <span className="warning">
              下方是此模板的上次预览，尚未反映当前修改。
            </span>
          )}
          {error && (
            <div className="actions">
              <button
                onClick={
                  /* 相同输入失败时显式重新尝试排版 */ () =>
                    queue.current?.submit(input, true)
                }
              >
                重新生成预览
              </button>
              {complete && result && (
                <button
                  onClick={
                    /* 排版失败仍允许查看已填好的临时 Word 文件 */ () =>
                      run(
                        /* 下载当前未保存资料的试填文档 */ () =>
                          download(
                            `/resume-previews/${result.id}/resume.docx`,
                            "当前模板预览.docx",
                          ),
                      )
                  }
                >
                  下载试填 Word
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {result?.pages && (
        <div
          className="print-preview"
          aria-busy={!updated}
          style={{
            width: zoom ? `${794 * zoom}px` : "100%",
            maxWidth: zoom ? "none" : "1000px",
          }}
        >
          {Array.from(
            { length: result.pages },
            /* 以矢量页面呈现真实分页，放大时保持文字清晰 */ (_, index) => (
              <PrintedPage
                key={`${result.id}.${index}`}
                path={`/resume-previews/${result.id}/page-${index + 1}.svg`}
                page={index + 1}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}
