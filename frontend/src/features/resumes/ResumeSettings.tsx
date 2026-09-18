import { FileDown, Save } from "lucide-react";
import TemplatePicker from "../../shared/components/TemplatePicker";
import { newDocument } from "../profile/document";
import type { ResumeLibraryProps } from "./ResumeLibrary";

/** 将名称、模板、保存和导出收拢在当前方案设置中，保留原有版本保护。 */
export default function ResumeSettings(props: ResumeLibraryProps) {
  const { draft, state } = props;
  const saved = state.resumes.find(
    /* 查找当前方案对应的持久化版本。 */ (item) => item.id === draft.id,
  );
  const templateUnavailable =
    !!draft.template_id &&
    !state.templates.some(
      /* 模板已删除时要求重新选择，避免导出失败。 */ (item) =>
        item.id === draft.template_id,
    );
  const busy = props.exporting || props.deleting;
  const invalid =
    busy || props.previewChanged || templateUnavailable || !draft.name.trim();
  return (
    <section className="resume-library-settings" aria-label="当前简历设置">
      <div className="resume-library-controls">
        <div className="resume-library-fields">
          <label>
            方案名称
            <input
              value={draft.name}
              disabled={busy}
              placeholder="为这份简历起个名字"
              onChange={
                /* 名称先进入本机草稿，保存或导出时持久化。 */ (event) =>
                  props.onChange({ ...draft, name: event.target.value })
              }
            />
          </label>
          <div className="resume-library-template">
            <TemplatePicker
              label="导出排版"
              guide="template-select"
              templates={state.templates}
              value={draft.template_id ?? ""}
              disabled={busy}
              onChange={
                /* 应用确认后的模板并补齐完整简历结构。 */ (id) =>
                  props.onChange({
                    ...draft,
                    template_id: id || null,
                    document: draft.document ?? newDocument(),
                  })
              }
            />
            <button
              className="text-button"
              disabled={busy}
              onClick={props.onTemplates}
            >
              管理模板
            </button>
          </div>
        </div>
        <div className="actions resume-library-actions">
          {saved && saved.version !== draft.version && (
            <button
              disabled={busy}
              onClick={
                /* 显式接受服务器保存的完整组合。 */ () => props.onChange(saved)
              }
            >
              载入服务器组合
            </button>
          )}
          <button
            data-guide="composition-save"
            disabled={invalid}
            onClick={props.onSave}
          >
            <Save size={15} />
            保存组合
          </button>
          <button
            className="primary"
            data-guide="export"
            disabled={invalid || (!draft.template_id && !draft.document)}
            onClick={props.onExport}
          >
            <FileDown size={15} />
            {props.exporting ? "正在生成并渲染…" : "导出 Word"}
          </button>
        </div>
      </div>
      {props.previewChanged && (
        <p className="warning" role="status">
          先提交修改并“用于当前简历”，再保存或导出。
        </p>
      )}
      {templateUnavailable && (
        <p className="warning" role="status">
          当前模板不可用，请重新选择导出排版。
        </p>
      )}
      {props.exporting && (
        <div className="export-progress" role="status">
          <span />
          正在生成文档并检查分页，完成后将出现在下方导出记录中…
        </div>
      )}
    </section>
  );
}
