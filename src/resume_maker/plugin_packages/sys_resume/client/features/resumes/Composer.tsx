import { Maximize2, Minimize2 } from "lucide-react";
import { useState } from "react";
import type {
  Resume,
  Revision,
  State,
} from "@resume-maker/plugin-sdk/shared/types/index";
import DocumentPreview from "@resume-maker/plugin-sdk/plugins/DocumentPreview";
import { templatePreviewInput } from "@resume-maker/plugin-sdk/shared/resume/templatePreviewInput";
import ContentPreview from "./ContentPreview";

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
            onChange={(event) => setZoom(Number(event.target.value))}
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
          {templateUnavailable && draft.document && (
            <p className="warning" role="status">
              当前模板暂不可用，已切换为内容预览。需要按模板排版时，请重新启用模板插件或选择可用模板。
            </p>
          )}
          {!draft.document ? (
            <p className="subtle">填写个人资料后，即可查看简历排版。</p>
          ) : templateUnavailable ? (
            <ContentPreview input={previewInput} />
          ) : (
            <DocumentPreview
              format="resume/v1"
              preferred={["ext.word/pages", "sys.resume/content"]}
              input={previewInput}
              templateId={draft.template_id}
              zoom={zoom}
              hidden={false}
              run={props.run}
            />
          )}
        </div>
      </section>
    </aside>
  );
}
