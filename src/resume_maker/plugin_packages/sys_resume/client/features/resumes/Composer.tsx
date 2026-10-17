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
import LayoutSettings from "./LayoutSettings";
import GenerateResumeButton from "./GenerateResumeButton";
import { LayoutSelectionContext } from "./layoutSelection";

interface Props {
  previewFocused: boolean;
  onFocusPreview: () => void;
  state: State;
  draft: Resume;
  revisions: Record<string, Revision>;
  previewSources: Record<string, Revision>;
  previewChanged?: boolean;
  onLayoutChange?: (value: NonNullable<Resume["document"]>) => void;
  exporting: boolean;
  deleting: boolean;
  onGenerate: () => void;
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
  // 未保存方案按草稿标识隔离，恢复相同内容也会作废旧排版请求
  const resumeIdentity = JSON.stringify([draft.id, draft.draft_id ?? null]);
  const [selection, setSelection] = useState({
    identity: "",
    key: "",
    request: 0,
  });
  const selected = selection.identity === resumeIdentity ? selection : null;

  /** 点选文字只更新当前编辑器目标，切换草稿后不沿用旧选择 */
  function selectLayoutItem(key: string) {
    setSelection((current) => ({
      identity: resumeIdentity,
      key,
      request: current.request + 1,
    }));
  }
  return (
    <DocumentPreview
      format="resume/v1"
      preferred={["ext.word/pages", "sys.resume/content"]}
      input={previewInput}
      templateId={draft.template_id}
      zoom={zoom}
      hidden={false}
      run={props.run}
      renderLayout={(selector, preview) => (
        <LayoutSelectionContext.Provider
          value={
            props.onLayoutChange
              ? {
                  key: selected?.key ?? "",
                  request: selected?.request ?? 0,
                  select: selectLayoutItem,
                }
              : null
          }
        >
          <aside className="composition-pane">
            <section className="preview-pane" aria-label="简历预览">
              <div className="preview-toolbar">
                <strong
                  title={
                    props.previewChanged
                      ? "预览包含尚未用于当前简历的经历内容，请保存并用于当前简历，或采用已保存版本"
                      : undefined
                  }
                >
                  {props.previewChanged
                    ? "经历预览 · 尚未用于简历"
                    : "简历预览"}
                </strong>
                {!templateUnavailable && draft.document && selector}
                {draft.document && props.onLayoutChange && (
                  <LayoutSettings
                    document={draft.document}
                    resumeIdentity={resumeIdentity}
                    previewInput={previewInput}
                    unavailable={templateUnavailable}
                    onChange={props.onLayoutChange}
                  />
                )}
                <GenerateResumeButton
                  exporting={props.exporting}
                  disabled={
                    props.deleting ||
                    !!props.previewChanged ||
                    templateUnavailable ||
                    !draft.name.trim() ||
                    (!draft.template_id && !draft.document)
                  }
                  title={
                    props.previewChanged
                      ? "先将编辑内容保存并用于当前简历，再生成简历"
                      : templateUnavailable
                        ? "请在当前简历中选择可用排版"
                        : "保存当前方案并生成可下载的简历"
                  }
                  onGenerate={props.onGenerate}
                />
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
                  aria-label={
                    props.previewFocused ? "退出放大预览" : "放大预览"
                  }
                  title={
                    props.previewFocused ? "退出放大预览（Esc）" : "放大预览"
                  }
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
                  preview
                )}
              </div>
            </section>
          </aside>
        </LayoutSelectionContext.Provider>
      )}
    />
  );
}
