import { arrayMove } from "@dnd-kit/sortable";
import {
  ArrowDown,
  ArrowUp,
  Download,
  FileDown,
  Maximize2,
  Minimize2,
  Plus,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import ResizeHandle from "../../shared/components/ResizeHandle";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import { useElementSize } from "../../shared/hooks/useElementSize";
import { download } from "../../shared/lib/api";
import { clamp, DEFAULT_LAYOUT } from "../../shared/lib/layout";
import type { Export, Resume, Revision, State } from "../../shared/types/index";
import { isCurrentExport, sameComposition } from "./composition.ts";
import PrintedPage from "./PrintedPage";
import DeleteResumeDialog from "./DeleteResumeDialog";
import ResumePreview from "../profile/ResumePreview";
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
  onEditProject: (id: string) => void;
  run: (work: () => Promise<void>) => void;
}

/** 编辑固定版本组合，默认展示所选模板的真实排版，保留内容调整与历史导出。 */
export default function Composer(props: Props) {
  const { draft, state, revisions, result } = props;
  const template = state.templates.find(
    /* 定位当前已识别的完整简历模板。 */ (item) =>
      item.id === draft.template_id,
  );
  const templateUnavailable = !!draft.template_id && !template;
  const [tab, setTab] = useState<"content" | "edit" | "print">("content");
  useEffect(
    /* 切换方案或模板时返回当前预览，避免把历史导出误认成新模板。 */ () => {
      setTab("content");
    },
    [draft.id, draft.template_id],
  );
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
  /** 按目标位置移动条目，并沿用当前组件的版本或组合保存规则。 */
  function move(from: number, to: number) {
    props.onChange({ ...draft, items: arrayMove(draft.items, from, to) });
  }
  const projectPreview = (
    <>
      {!draft.items.length && (
        <div className="empty compact preview-empty">
          <p>从左侧勾选项目</p>
          <span>选择经历版本与亮点，再调整项目顺序。</span>
        </div>
      )}
      <SortableList
        key={draft.id}
        items={draft.items.map(
          /* 逐项转换数据，保留当前业务需要的字段。 */ (item) => ({
            id: item.project_id,
            label:
              (
                props.previewSources[item.project_id] ??
                revisions[item.revision_id]
              )?.content.title || "项目",
          }),
        )}
        disabled={draft.items.some(
          /* 检查条目是否满足当前选择或校验条件。 */ (item) =>
            !revisions[item.revision_id],
        )}
        onMove={move}
      >
        {draft.items.map(
          /* 按稳定标识生成对应的列表条目。 */ (item, index) => {
            const revision =
              props.previewSources[item.project_id] ??
              revisions[item.revision_id];
            if (!revision)
              return <p key={item.project_id}>正在读取经历版本…</p>;
            const value = revision.content;
            return (
              <SortableItem
                as="article"
                className="resume-project"
                key={item.project_id}
                id={item.project_id}
                label={`项目 ${value.title}`}
              >
                {
                  /* 将排序手柄嵌入对应业务条目的操作区。 */ (handle) => (
                    <>
                      <div className="resume-project-title">
                        <strong>{value.title}</strong>
                        <div className="row">
                          <button
                            className="icon-button"
                            aria-label={`上移项目 ${value.title}`}
                            disabled={index === 0}
                            onClick={
                              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                                move(index, index - 1)
                            }
                          >
                            <ArrowUp size={13} />
                          </button>
                          {handle}
                          <button
                            className="icon-button"
                            aria-label={`下移项目 ${value.title}`}
                            disabled={index === draft.items.length - 1}
                            onClick={
                              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                                move(index, index + 1)
                            }
                          >
                            <ArrowDown size={13} />
                          </button>
                          <button
                            className="icon-button"
                            aria-label={`移除项目 ${value.title}`}
                            onClick={
                              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                                props.onChange({
                                  ...draft,
                                  items: draft.items.filter(
                                    /* 保留满足当前范围或有效性条件的条目。 */ (
                                      _,
                                      i,
                                    ) => i !== index,
                                  ),
                                })
                            }
                          >
                            <X size={13} />
                          </button>
                        </div>
                      </div>
                      <span className="resume-period">
                        {value.period} {value.role}
                      </span>
                      {value.stack.length > 0 && (
                        <p>
                          <b>技术栈：</b>
                          {value.stack.join("、")}
                        </p>
                      )}
                      {value.description && (
                        <p>
                          <b>项目描述：</b>
                          {value.description}
                        </p>
                      )}
                      {value.highlights
                        .filter(
                          /* 按编辑区当前顺序显示勾选条目，取消后重选不改变位置。 */ (
                            h,
                          ) => item.highlight_ids.includes(h.id),
                        )
                        .map(
                          /* 按稳定标识生成对应的列表条目。 */ (h) => (
                            <p key={h.id}>
                              <b>{h.title}：</b>
                              {h.text}
                            </p>
                          ),
                        )}
                      {!value.highlights.length && !value.description && (
                        <p className="subtle">
                          尚未填写项目经历，可先分析源码。
                        </p>
                      )}
                      <span className="version-note">
                        {revision !== revisions[item.revision_id]
                          ? `实时预览 · 基于 r${revision.number}`
                          : `固定引用 r${revision.number}`}
                      </span>
                      {state.branches.find(
                        /* 定位与当前标识或条件匹配的条目。 */ (branch) =>
                          branch.id === revision.branch_id,
                      )?.head_revision !== revision.id && (
                        <button
                          className="text-button revision-update"
                          onClick={
                            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                              props.onEditProject(item.project_id)
                          }
                        >
                          有更新的经历版本 · 查看
                        </button>
                      )}
                    </>
                  )
                }
              </SortableItem>
            );
          },
        )}
      </SortableList>
    </>
  );
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
              <option value="">内置 · 完整简历</option>
              {templateUnavailable && (
                <option value={draft.template_id!}>请重新选择完整模板</option>
              )}
              {state.templates.map(
                /* 按稳定标识生成对应的列表条目。 */ (t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ),
              )}
            </select>
          </label>
          <button className="text-button" onClick={props.onTemplates}>
            管理模板
          </button>
        </div>
        {template && (
          <p className="subtle">
            按已确认映射替换个人信息、照片和栏目，保留模板版式；右侧模板预览随资料修改自动更新。
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
      </header>
      {deleteTarget && (
        <DeleteResumeDialog
          resume={deleteTarget}
          onClose={/* 取消删除并返回组合编辑。 */ () => setDeleteTarget(null)}
          onConfirm={
            /* 关闭确认弹窗并删除已经确认的方案。 */ () => {
              setDeleteTarget(null);
              props.onDelete(deleteTarget);
              setTab("content");
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
        <nav className="tabs preview-tabs">
          <button
            className={tab === "content" ? "active" : ""}
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () => setTab("content")
            }
          >
            {draft.template_id ? "模板预览" : "内容预览"}
          </button>
          {draft.template_id && (
            <button
              className={tab === "edit" ? "active" : ""}
              onClick={
                /* 保留项目排序和版本调整的内容视图。 */ () => setTab("edit")
              }
            >
              编辑内容
            </button>
          )}
          <button
            className={tab === "print" ? "active" : ""}
            disabled={!result}
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () => setTab("print")
            }
          >
            上次导出预览{result?.pages ? ` · ${result.pages} 页` : ""}
          </button>
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
        </nav>
        <div className="composition-scroll">
          {tab === "print" && result && (
            <div className="export-result">
              <strong>
                {currentExport ? "当前组合已导出" : "上次导出"}
                {result.pages ? ` · ${result.pages} 页` : " · Word 已生成"}
              </strong>
              {!currentExport && (
                <span className="warning">
                  组合已变化，重新导出后更新文件与预览。
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
          )}
          <TemplatePreview
            input={templateUnavailable ? null : previewInput}
            templateId={template?.id}
            hidden={!template || tab !== "content"}
            run={props.run}
          />
          {tab === "print" && result ? (
            <div className="print-preview">
              {Array.from(
                { length: result.pages ?? 0 },
                /* 执行当前异步流程，保持请求结果与所属组件状态一致。 */ (
                  _,
                  i,
                ) => (
                  <PrintedPage
                    key={`${result.id}.${i}`}
                    exportId={result.id}
                    page={i + 1}
                  />
                ),
              )}
            </div>
          ) : templateUnavailable && tab === "content" ? (
            <p className="warning" role="status">
              当前完整模板不可用，请重新选择模板或在“管理模板”中导入 Word 进行
              AI 识别。
            </p>
          ) : !template || tab === "edit" ? (
            <>
              {template && (
                <p className="subtle">
                  此视图用于调整项目内容与顺序；模板的字体和分页请查看“模板预览”。
                </p>
              )}
              <ResumePreview draft={draft} projects={projectPreview} />
            </>
          ) : null}
        </div>
      </section>
    </aside>
  );
}
