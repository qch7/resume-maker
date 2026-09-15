import {
  Download,
  FileDown,
  Maximize2,
  Minimize2,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { useRef, useState, type CSSProperties } from "react";
import ResizeHandle from "../../shared/components/ResizeHandle";
import TemplateOptions from "../../shared/components/TemplateOptions";
import { useElementSize } from "../../shared/hooks/useElementSize";
import { download } from "../../shared/lib/api";
import { clamp, DEFAULT_LAYOUT } from "../../shared/lib/layout";
import type { Export, Resume, Revision, State } from "../../shared/types/index";
import { isCurrentExport, sameComposition } from "./composition.ts";
import DeleteResumeDialog from "./DeleteResumeDialog";
import { newDocument } from "../profile/document";
import TemplatePreview from "./TemplatePreview";
import { templatePreviewInput } from "./templatePreviewInput";

interface Props {
  settingsHeight: number;
  onSettingsHeight: (value: number) => void;
  previewFocused: boolean;
  onFocusPreview: () => void;
  state: State;
  draft: Resume;
  revisions: Record<string, Revision>;
  previewSources: Record<string, Revision>;
  previewChanged: boolean;
  result: Export | null;
  exporting: boolean;
  deleting: boolean;
  onChange: (value: Resume) => void;
  onChoose: (id: string) => void;
  onSave: () => void;
  onExport: () => void;
  onNew: () => void;
  onDelete: (resume: Resume) => void;
  onTemplates: () => void;
  run: (work: () => Promise<void>) => void;
}

/** 编辑固定版本组合并展示真实排版，项目编排由栏目工作区管理。 */
export default function Composer(props: Props) {
  const { draft, state, revisions, result } = props;
  const template = state.templates.find(
    /* 定位当前已识别的完整简历模板。 */ (item) =>
      item.id === draft.template_id,
  );
  const templateUnavailable = !!draft.template_id && !template;
  const [zoom, setZoom] = useState(0);
  const previewInput = templatePreviewInput(
    draft,
    revisions,
    props.previewSources,
  );
  const [deleteTarget, setDeleteTarget] = useState<Resume | null>(null);
  const pane = useRef<HTMLElement>(null);
  const size = useElementSize(pane);
  const settingsMax = Math.max(80, size.height - 188);
  const settingsHeight = clamp(props.settingsHeight, 80, settingsMax);
  const saved = state.resumes.find(
    /* 定位与当前标识或条件匹配的条目。 */ (r) => r.id === draft.id,
  );
  const dirty = !sameComposition(saved, draft);
  const currentExport = !props.previewChanged && isCurrentExport(result, draft);
  return (
    <aside
      className="composition-pane"
      ref={pane}
      style={{ "--settings-height": `${settingsHeight}px` } as CSSProperties}
    >
      <header className="composition-header">
        <div className="section-heading">
          <h2>当前简历</h2>
          <span className={`tag ${dirty ? "warning-tag" : "success-tag"}`}>
            {dirty ? "组合未保存" : "组合已保存"}
          </span>
        </div>
        <div className="resume-picker">
          <select
            aria-label="简历方案"
            disabled={props.deleting}
            value={draft.id}
            onChange={
              /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                props.onChoose(e.target.value)
            }
          >
            {!draft.id && <option value="">未命名方案</option>}
            {state.resumes.map(
              /* 按稳定标识生成对应的列表条目。 */ (r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ),
            )}
          </select>
          <button
            className="icon-button"
            aria-label="新建简历方案"
            title="新建简历方案"
            disabled={props.deleting}
            onClick={props.onNew}
          >
            <Plus size={17} />
          </button>
          <button
            className="icon-button danger-hover"
            aria-label="删除当前简历方案"
            title={draft.id ? "删除当前简历方案" : "当前没有已保存的方案"}
            disabled={!draft.id || props.exporting || props.deleting}
            onClick={
              /* 固定待删除方案，确认时不会误操作其他选择。 */ () =>
                setDeleteTarget(draft)
            }
          >
            <Trash2 size={17} />
          </button>
        </div>
        <label>
          方案名称
          <input
            value={draft.name}
            onChange={
              /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                props.onChange({ ...draft, name: e.target.value })
            }
          />
        </label>
        <div className="template-picker">
          <label>
            导出排版
            <select
              data-guide="template-select"
              value={draft.template_id ?? ""}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                  props.onChange({
                    ...draft,
                    template_id: e.target.value || null,
                    document: draft.document ?? newDocument(),
                  })
              }
            >
              {templateUnavailable && (
                <option value={draft.template_id!}>请重新选择完整模板</option>
              )}
              <TemplateOptions templates={state.templates} />
            </select>
          </label>
          <button className="text-button" onClick={props.onTemplates}>
            管理模板
          </button>
        </div>
        {template && (
          <p className="subtle">
            按已确认映射替换个人信息、照片和栏目，保留模板版式；右侧简历预览随资料修改自动更新。
          </p>
        )}
        <div className="actions">
          {saved && saved.version !== draft.version && (
            <button
              onClick={
                /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                  props.onChange(saved)
              }
            >
              载入服务器组合
            </button>
          )}
          <button
            data-guide="composition-save"
            onClick={props.onSave}
            disabled={
              props.deleting ||
              props.previewChanged ||
              templateUnavailable ||
              !draft.name.trim()
            }
          >
            <Save size={15} />
            保存组合
          </button>
          <button
            className="primary"
            data-guide="export"
            onClick={props.onExport}
            disabled={
              props.exporting ||
              props.previewChanged ||
              props.deleting ||
              (!draft.template_id && !draft.document) ||
              templateUnavailable ||
              !draft.name.trim()
            }
          >
            <FileDown size={15} />
            {props.exporting ? "正在生成并渲染…" : "导出 Word"}
          </button>
        </div>
        {props.previewChanged && (
          <p className="subtle" role="status">
            正在实时预览编辑内容。提交修改并点击“用于当前简历”后，可保存和导出此内容。
          </p>
        )}
        <div className="composition-summary" aria-live="polite">
          <span>
            已选 <b key={draft.items.length}>{draft.items.length}</b> 个项目
          </span>
          <span>
            <b>
              {draft.items.reduce(
                /* 执行当前异步流程，保持请求结果与所属组件状态一致。 */ (
                  sum,
                  item,
                ) => sum + item.highlight_ids.length,
                0,
              )}
            </b>{" "}
            条亮点
          </span>
        </div>
        {props.exporting && (
          <div className="export-progress" role="status">
            <span />
            正在生成文档并检查分页…
          </div>
        )}
        {result && (
          <details className="export-downloads">
            <summary>
              {currentExport
                ? "下载已导出的文件"
                : "上次导出文件（内容已变化）"}
            </summary>
            <div className="export-result">
              <strong>
                {currentExport ? "当前组合已导出" : "上次导出"}
                {result.pages ? ` · ${result.pages} 页` : " · Word 已生成"}
              </strong>
              {!currentExport && (
                <span className="warning">
                  组合已变化，以下下载仍是上次导出的文件。
                </span>
              )}
              <span className="subtle">
                {new Date(result.created_at).toLocaleString()}
              </span>
              {result.render_error && (
                <p className="warning">{result.render_error}</p>
              )}
              <div className="actions">
                <button
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      props.run(
                        /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                          download(
                            `/exports/${result.id}/resume.docx`,
                            `${draft.name}.docx`,
                          ),
                      )
                  }
                >
                  <Download size={14} />
                  Word
                </button>
                {result.pages && (
                  <button
                    onClick={
                      /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                        props.run(
                          /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                            download(
                              `/exports/${result.id}/resume.pdf`,
                              `${draft.name}.pdf`,
                            ),
                        )
                    }
                  >
                    PDF
                  </button>
                )}
                <button
                  className="text-button"
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      props.run(
                        /* 在草稿刷新成功后执行当前业务操作。 */ () =>
                          download(
                            `/exports/${result.id}/manifest.json`,
                            "export-manifest.json",
                          ),
                      )
                  }
                >
                  版本清单
                </button>
              </div>
            </div>
          </details>
        )}
      </header>
      {deleteTarget && (
        <DeleteResumeDialog
          resume={deleteTarget}
          onClose={/* 取消删除并返回组合编辑。 */ () => setDeleteTarget(null)}
          onConfirm={
            /* 关闭确认弹窗并删除已经确认的方案。 */ () => {
              setDeleteTarget(null);
              props.onDelete(deleteTarget);
            }
          }
        />
      )}
      <ResizeHandle
        className="settings-resize"
        label="调整设置与预览高度"
        axis="y"
        value={settingsHeight}
        min={80}
        max={settingsMax}
        onChange={props.onSettingsHeight}
        onReset={
          /* 恢复该区域的默认布局尺寸。 */ () =>
            props.onSettingsHeight(DEFAULT_LAYOUT.settings)
        }
      />
      <section className="preview-pane" aria-label="简历预览">
        <div className="preview-toolbar">
          <strong>简历预览</strong>
          <select
            aria-label="预览缩放"
            value={zoom}
            onChange={
              /* 缩放矢量页面，零值表示适应可用宽度。 */ (event) =>
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
