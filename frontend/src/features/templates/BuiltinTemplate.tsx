import { useState } from "react";
import type { Resume, Revision } from "../../shared/types";
import TemplatePreview from "../resumes/TemplatePreview";
import { templatePreviewInput } from "../resumes/templatePreviewInput";

/** 使用当前未保存资料预览内置 Word 版式 */
export default function BuiltinTemplate({
  active,
  resume,
  revisions,
  previewSources,
  run,
}: {
  active: boolean;
  resume: Resume;
  revisions: Record<string, Revision>;
  previewSources: Record<string, Revision>;
  run: (work: () => Promise<void>) => void;
}) {
  const [zoom, setZoom] = useState(0);
  const input = templatePreviewInput(
    { ...resume, template_id: null },
    revisions,
    previewSources,
  );
  return (
    <div className="builtin-template">
      <header className="builtin-template-header">
        <div>
          <h2>内置 · 完整简历</h2>
          <p className="subtle">
            自动排版个人信息、照片和全部栏目。内容可在“个人信息”和“栏目编排”中编辑。
          </p>
        </div>
        <div className="actions">
          {!resume.template_id && (
            <span className="tag success-tag">当前使用</span>
          )}
          <select
            aria-label="内置模板预览缩放"
            value={zoom}
            onChange={
              /* 缩放已有的 Word 矢量分页 */ (event) =>
                setZoom(Number(event.target.value))
            }
          >
            <option value={0}>适应宽度</option>
            <option value={0.75}>75%</option>
            <option value={1}>100%</option>
            <option value={1.25}>125%</option>
            <option value={1.5}>150%</option>
            <option value={2}>200%</option>
          </select>
        </div>
      </header>
      <div className="builtin-template-preview" aria-label="内置模板预览">
        <TemplatePreview
          input={active ? input : null}
          templateId={null}
          zoom={zoom}
          hidden={!active}
          run={run}
        />
      </div>
    </div>
  );
}
