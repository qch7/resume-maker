import { useState } from "react";
import PathInput from "../../shared/components/PathInput";
import { api } from "../../shared/lib/api";
import type { Inspection } from "../../shared/types";

/** 独立保留仅替换项目区的手动模板工具。 */
export default function ManualTemplate(props: {
  onChanged: () => Promise<void>;
}) {
  const [templatePath, setTemplatePath] = useState(""),
    [templateName, setTemplateName] = useState("");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [start, setStart] = useState(""),
    [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  /** 在当前工具内显示读取和登记结果，不影响完整模板编辑状态。 */
  async function run(work: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await work();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="manual-template-panel">
      {" "}
      <details className="manual-template">
        <summary>仅替换项目经历（手动选择）</summary>
        <p className="subtle">
          保留模板其他栏目，仅替换选定的项目经历区域。原文件保留，每次导入创建独立模板版本。
        </p>
        <PathInput
          label="Word 模板路径"
          kind="docx"
          placeholder="D:\...\简历.docx"
          value={templatePath}
          disabled={busy}
          onChange={
            /* 选择或输入新模板后撤销旧段落检查。 */ (value) => {
              setTemplatePath(value);
              setInspection(null);
            }
          }
        />
        <button
          disabled={busy || !templatePath.trim()}
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () =>
              run(
                /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                  const value = await api<Inspection>(
                    "/templates/inspect",
                    "POST",
                    { path: templatePath },
                  );
                  setInspection(value);
                  setStart(value.suggested_start?.toString() ?? "");
                  setEnd(value.suggested_end?.toString() ?? "");
                  setTemplateName(value.file_name.replace(/\.docx$/i, ""));
                },
              )
          }
        >
          读取模板
        </button>
        {inspection && (
          <>
            <label>
              模板名称
              <input
                value={templateName}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    setTemplateName(e.target.value)
                }
              />
            </label>
            <label>
              替换起点（首个项目标题）
              <select
                value={start}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    setStart(e.target.value)
                }
              >
                <option value="">选择段落</option>
                {inspection.paragraphs.map(
                  /* 按稳定标识生成对应的列表条目。 */ (p) => (
                    <option key={p.index} value={p.index}>
                      {p.index + 1}. {p.text.slice(0, 90) || "空段落"}
                    </option>
                  ),
                )}
              </select>
            </label>
            <label>
              替换终点（下一个需要保留的栏目）
              <select
                value={end}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    setEnd(e.target.value)
                }
              >
                <option value="">选择段落</option>
                {inspection.paragraphs.map(
                  /* 按稳定标识生成对应的列表条目。 */ (p) => (
                    <option key={p.index} value={p.index}>
                      {p.index + 1}. {p.text.slice(0, 90) || "空段落"}
                    </option>
                  ),
                )}
              </select>
            </label>
            {start && end && (
              <div className="template-range">
                <strong>将替换以下内容</strong>
                {inspection.paragraphs
                  .filter(
                    /* 保留满足当前范围或有效性条件的条目。 */ (p) =>
                      p.index >= Number(start) &&
                      p.index < Number(end) &&
                      p.text.trim(),
                  )
                  .map(
                    /* 按稳定标识生成对应的列表条目。 */ (p) => (
                      <p key={p.index}>{p.text}</p>
                    ),
                  )}
              </div>
            )}
            <button
              className="primary"
              disabled={busy || !start || !end || Number(start) >= Number(end)}
              onClick={
                /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                      await api("/templates", "POST", {
                        path: templatePath,
                        name: templateName,
                        start: Number(start),
                        end: Number(end),
                      });
                      await props.onChanged();
                      setNotice("模板已保存，可返回其他板块在简历中选择。");
                    },
                  )
              }
            >
              保存模板版本
            </button>
          </>
        )}
      </details>
      {notice && <p role="status">{notice}</p>}
    </div>
  );
}
