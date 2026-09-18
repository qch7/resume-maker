import { FileDown, FileText, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Export, Resume, State } from "../../shared/types";
import ResumeSettings from "./ResumeSettings";
import ExportHistory from "./ExportHistory";
import DeleteResumeDialog from "./DeleteResumeDialog";
import { sameComposition } from "./composition";

export interface ResumeLibraryProps {
  state: State;
  draft: Resume;
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
  onClose: () => void;
  notice: { text: string; error?: boolean } | null;
  onDismissNotice: () => void;
}

/** 在统一简历库内切换方案、选择排版并管理每次导出的独立文件 */
export default function ResumeLibrary(props: ResumeLibraryProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [query, setQuery] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Resume | null>(null);
  const { state, draft } = props;
  const dirty = !sameComposition(
    state.resumes.find(
      /* 当前卡片的保存状态跟随实际草稿内容 */ (item) => item.id === draft.id,
    ),
    draft,
  );
  const resumes = draft.id
    ? state.resumes.map(
        /* 当前方案展示本机草稿名；保存前也能通过搜索找到 */ (item) =>
          item.id === draft.id ? draft : item,
      )
    : [draft, ...state.resumes];
  const visible = resumes.filter(
    /* 方案搜索忽略大小写和首尾空格 */ (item) =>
      item.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  useEffect(
    /* 原生模态层约束焦点；关闭后回到顶部统一入口 */ () => {
      const element = dialog.current!;
      const trigger = document.activeElement;
      element.showModal();
      return /* 卸载时恢复触发位置；继续编辑时无需重新定位 */ () => {
        element.close();
        if (trigger instanceof HTMLElement && trigger.isConnected)
          trigger.focus({ preventScroll: true });
      };
    },
    [],
  );
  return createPortal(
    <dialog
      ref={dialog}
      className="resume-library-dialog"
      aria-labelledby={titleId}
      onCancel={
        /* 子模板库和删除确认通过 Portal 冒泡取消事件时且只关闭对应子窗口 */ (
          event,
        ) => {
          event.stopPropagation();
          if (event.target === event.currentTarget) props.onClose();
        }
      }
      onKeyDown={
        /* Escape 仅关闭当前模态层且不穿透到工作台的放大预览 */ (event) => {
          if (event.key === "Escape") event.stopPropagation();
        }
      }
    >
      <header className="library-titlebar">
        <div>
          <FileDown size={22} />
          <h2 id={titleId}>简历库</h2>
        </div>
        <button
          className="icon-button"
          aria-label="关闭简历库"
          onClick={props.onClose}
        >
          <X size={19} />
        </button>
      </header>
      {props.notice && (
        <div
          className={`resume-library-notice ${props.notice.error ? "warning" : ""}`}
          role={props.notice.error ? "alert" : "status"}
        >
          <span>{props.notice.text}</span>
          <button
            className="icon-button"
            aria-label="关闭操作提示"
            onClick={props.onDismissNotice}
          >
            <X size={15} />
          </button>
        </div>
      )}
      <div className="resume-library-body">
        <aside className="resume-library-sidebar" aria-label="简历方案">
          <div className="section-heading">
            <h3>
              我的简历 <span className="count-badge">{resumes.length}</span>
            </h3>
            <button
              className="icon-button"
              title="新建简历方案"
              aria-label="新建简历方案"
              disabled={props.deleting || props.exporting}
              onClick={
                /* 新建后清空筛选；让新方案始终可见 */ () => {
                  setQuery("");
                  props.onNew();
                }
              }
            >
              <Plus size={17} />
            </button>
          </div>
          <label className="resume-library-search">
            <Search size={16} />
            <input
              aria-label="搜索简历方案"
              placeholder="搜索简历方案"
              value={query}
              onChange={
                /* 即时筛选方案列表 */ (event) => setQuery(event.target.value)
              }
            />
          </label>
          <div className="resume-library-list">
            {visible.map(
              /* 选择方案后沿用其本机草稿且不自动保存或覆盖资料 */ (item) => (
                <div
                  key={item.id || "new"}
                  className={`resume-library-item ${item.id === draft.id ? "selected" : ""}`}
                >
                  <button
                    className="resume-library-select"
                    aria-current={item.id === draft.id ? "true" : undefined}
                    disabled={props.deleting || props.exporting}
                    onClick={
                      /* 当前方案无需重复加载以免覆盖未保存输入 */ () => {
                        if (item.id !== draft.id) props.onChoose(item.id);
                      }
                    }
                  >
                    <FileText size={20} />
                    <span>
                      <strong title={item.name || "未命名方案"}>
                        {item.name || "未命名方案"}
                      </strong>
                      <span className="resume-library-item-summary">
                        <span>{item.items.length} 个项目</span>
                        <span>
                          {item.items.reduce(
                            /* 卡片汇总该方案选择的全部亮点 */ (sum, entry) =>
                              sum + entry.highlight_ids.length,
                            0,
                          )}{" "}
                          条亮点
                        </span>
                      </span>
                      <span
                        className={`tag ${item.id === draft.id && dirty ? "warning-tag" : "success-tag"}`}
                      >
                        {item.id === draft.id && dirty
                          ? "组合未保存"
                          : "组合已保存"}
                      </span>
                    </span>
                  </button>
                  <button
                    className="icon-button danger-hover resume-library-delete"
                    aria-label={`删除简历方案“${item.name || "未命名方案"}”`}
                    title={`删除简历方案“${item.name || "未命名方案"}”`}
                    disabled={!item.id || props.deleting || props.exporting}
                    onClick={
                      /* 删除入口独立于选择按钮；固定目标且不切换正在编辑的方案 */ () =>
                        setDeleteTarget(item)
                    }
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ),
            )}
            {!visible.length && <p className="subtle">没有匹配的简历方案。</p>}
          </div>
        </aside>
        <main className="resume-library-content">
          <ResumeSettings {...props} />
          <ExportHistory
            key={draft.id}
            draft={draft}
            result={props.result}
            previewChanged={props.previewChanged}
          />
        </main>
      </div>
      {deleteTarget && (
        <DeleteResumeDialog
          resume={deleteTarget}
          onClose={/* 取消时保留方案及所有文件 */ () => setDeleteTarget(null)}
          onConfirm={
            /* 仅删除卡片上经过确认的方案且不依赖当前选择 */ () => {
              setDeleteTarget(null);
              props.onDelete(deleteTarget);
            }
          }
        />
      )}
    </dialog>,
    document.body,
  );
}
