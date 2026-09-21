import { FileScan } from "lucide-react";
import { download } from "../../shared/lib/api";
import PrintedPage from "../resumes/PrintedPage";
import type { TemplateTrialPreview } from "./types";

/** 更新期间保留上次生成的 Word 页面并提示状态 */
export default function TemplateTrial({
  preview,
  stale,
  taskId,
  name,
  pending,
  run,
}: {
  preview: TemplateTrialPreview | null;
  stale: boolean;
  taskId: string;
  name: string;
  pending: string;
  run: (work: () => Promise<void>) => void;
}) {
  if (!preview)
    return (
      <div className="template-trial-empty" role="status">
        <FileScan size={32} />
        <h3>在这里查看 Word 实际效果</h3>
        <p>{pending || "点击下方“生成试填预览”，查看当前资料填入后的排版。"}</p>
        <p className="subtle">
          需要修正时，在右侧选择对应内容，调整后重新生成预览。
        </p>
      </div>
    );
  return (
    <>
      {stale && (
        <p className="template-preview-stale" role="status">
          已修改，下面仍是上一次的效果。点击“更新试填预览”查看最新结果。
        </p>
      )}
      <div className="template-preview-scroll">
        <div className="template-preview">
          <div className="actions">
            <button
              disabled={stale}
              title={stale ? "更新试填预览后即可下载" : undefined}
              onClick={
                /* 下载当前试填生成的 Word，禁止把旧结果当成新结果 */ () =>
                  run(
                    /* 将实际文件交给浏览器下载 */ () =>
                      download(
                        `/templates/analyses/${taskId}/previews/${preview.id}/resume.docx`,
                        `${name}-试填.docx`,
                      ),
                  )
              }
            >
              下载试填 Word
            </button>
            {!!preview.pages && (
              <button
                disabled={stale}
                title={stale ? "更新试填预览后即可下载" : undefined}
                onClick={
                  /* PDF 和当前 Word 使用同一次排版结果 */ () =>
                    run(
                      /* 下载 Word 实际生成的 PDF */ () =>
                        download(
                          `/templates/analyses/${taskId}/previews/${preview.id}/resume.pdf`,
                          `${name}-试填.pdf`,
                        ),
                    )
                }
              >
                下载 PDF
              </button>
            )}
          </div>
          {preview.render_error && (
            <p className="template-notice" role="status">
              {preview.render_error}
            </p>
          )}
          {Array.from(
            { length: preview.pages ?? 0 },
            /* 按真实页序展示，修正填写规则不会拆散或重建旧页面 */ (
              _,
              index,
            ) => (
              <PrintedPage
                key={`${preview.id}-${index}`}
                path={`/templates/analyses/${taskId}/previews/${preview.id}/page-${index + 1}.svg`}
                page={index + 1}
              />
            ),
          )}
        </div>
      </div>
    </>
  );
}
