import { Maximize2, Minimize2 } from "lucide-react";
import { useState } from "react";
import type { Resume, Revision, State } from "../../shared/types/index";
import TemplatePreview from "./TemplatePreview";
import { templatePreviewInput } from "./templatePreviewInput";

interface Props {
  previewFocused: boolean;
  onFocusPreview: () => void;
  state: State;
  draft: Resume;
  revisions: Record<string, Revision>;
  previewSources: Record<string, Revision>;
  run: (work: () => Promise<void>) => void;
}

/** 工作台右侧显示实时预览 */
export default function Composer(props: Props) {
  const { draft, state, revisions } = props;
  const templateUnavailable =
    !!draft.template_id &&
    !state.templates.some(
      /* 检查当前模板是否仍可用于排版 */ (item) =>
        item.id === draft.template_id,
    );
  const [zoom, setZoom] = useState(0);
  const previewInput = templatePreviewInput(
    draft,
    revisions,
    props.previewSources,
  );
  return (
    <aside className="composition-pane">
      <section className="preview-pane" aria-label="简历预览">
        <div className="preview-toolbar">
          <strong>简历预览</strong>
          <select
            aria-label="预览缩放"
            value={zoom}
            onChange={
              /* 缩放矢量页面，零值表示适应可用宽度 */ (event) =>
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
          <button
            className="icon-button preview-focus"
            aria-label={props.previewFocused ? "退出放大预览" : "放大预览"}
            title={props.previewFocused ? "退出放大预览（Esc）" : "放大预览"}
            aria-pressed={props.previewFocused}
            onClick={props.onFocusPreview}
          >
            {props.previewFocused ? (
              <Minimize2 size={16} />
            ) : (
              <Maximize2 size={16} />
            )}
          </button>
        </div>
        <div className="composition-scroll">
          {templateUnavailable ? (
            <p className="warning" role="status">
              当前完整模板不可用，请重新选择模板或在“管理模板”中导入 Word 进行
              AI 识别。
            </p>
          ) : !draft.document ? (
            <p className="subtle">填写个人资料后，即可查看简历排版。</p>
          ) : null}
          <TemplatePreview
            input={templateUnavailable ? null : previewInput}
            templateId={draft.template_id}
            zoom={zoom}
            hidden={templateUnavailable || !draft.document}
            run={props.run}
          />
        </div>
      </section>
    </aside>
  );
}
