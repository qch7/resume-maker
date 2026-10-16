import type { ResumeDocument } from "@resume-maker/plugin-sdk/shared/types/index";
import {
  pageLayout,
  withPageLayout,
  type PageLayout,
} from "@resume-maker/plugin-sdk/shared/resume/pageLayout";

/** 在已有预览工具栏设置页数预算，格式调整只作用于当前方案 */
export default function LayoutSettings({
  document,
  onChange,
}: {
  document: ResumeDocument;
  onChange: (value: ResumeDocument) => void;
}) {
  const value = pageLayout(document);
  /** 将本次选择写入方案草稿，真实 Word 预览自动更新 */
  function update(patch: Partial<PageLayout>) {
    onChange(withPageLayout(document, { ...value, ...patch }));
  }
  return (
    <details className="resume-layout-settings">
      <summary>版面设置</summary>
      <div role="group" aria-label="当前简历版面设置">
        <label>
          页数预算
          <select
            aria-label="页数预算"
            value={value.target_pages}
            onChange={(event) =>
              update({ target_pages: Number(event.target.value) })
            }
          >
            {[1, 2, 3].map((count) => (
              <option key={count} value={count}>
                {count} 页
              </option>
            ))}
          </select>
        </label>
        <label>
          正文字号
          <select
            aria-label="正文字号"
            value={value.font_size ?? ""}
            onChange={(event) =>
              update({
                font_size: event.target.value
                  ? Number(event.target.value)
                  : undefined,
              })
            }
          >
            <option value="">沿用模板</option>
            {[9, 9.5, 10, 10.5, 11, 11.5, 12].map((size) => (
              <option key={size} value={size}>
                {size} 磅
              </option>
            ))}
          </select>
        </label>
        <label>
          段落间距
          <select
            aria-label="段落间距"
            value={value.space_after ?? ""}
            onChange={(event) =>
              update({
                space_after: event.target.value
                  ? Number(event.target.value)
                  : undefined,
              })
            }
          >
            <option value="">沿用模板</option>
            {[0, 1, 2, 3, 4, 6, 8].map((space) => (
              <option key={space} value={space}>
                {space} 磅
              </option>
            ))}
          </select>
        </label>
        <label>
          行距
          <select
            aria-label="行距"
            value={value.line_spacing ?? ""}
            onChange={(event) =>
              update({
                line_spacing: event.target.value
                  ? Number(event.target.value)
                  : undefined,
              })
            }
          >
            <option value="">沿用模板</option>
            {[1, 1.05, 1.1, 1.2, 1.3, 1.5].map((space) => (
              <option key={space} value={space}>
                {space} 倍
              </option>
            ))}
          </select>
        </label>
        <label className="resume-layout-inline">
          <input
            type="checkbox"
            checked={!!value.honors_inline}
            onChange={(event) =>
              update({ honors_inline: event.target.checked })
            }
          />
          荣誉紧凑行
        </label>
        <div className="actions">
          <button
            onClick={() =>
              update({
                font_size: 9.5,
                space_after: 1,
                line_spacing: 1.05,
                honors_inline: true,
              })
            }
          >
            试用紧凑排版
          </button>
          <button
            onClick={() =>
              onChange(
                withPageLayout(document, { target_pages: value.target_pages }),
              )
            }
          >
            恢复模板排版
          </button>
        </div>
        <p>
          适用于内置版式及 Word
          模板。正文、间距及荣誉排法自动更新预览，不删减文字；准确页数以 Word
          排版为准。保存方案后保留选择。
        </p>
      </div>
    </details>
  );
}
