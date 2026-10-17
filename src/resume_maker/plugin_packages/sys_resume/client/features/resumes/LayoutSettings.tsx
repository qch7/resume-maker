import { Link2, Unlink2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ResumeDocument } from "@resume-maker/plugin-sdk/shared/types/index";
import {
  pageLayout,
  resetPageLayout,
  withPageLayout,
  type ItemStyle,
  type PageLayout,
} from "@resume-maker/plugin-sdk/shared/resume/pageLayout";
import {
  declaredItemStyle,
  itemLinked,
  ITEM_TYPE_LABELS,
  layoutItems,
  setItemLinked,
  updateItemStyle,
  validItemStyleNumber,
  type LayoutPreviewItem,
} from "@resume-maker/plugin-sdk/shared/resume/itemLayout";
import {
  currentFitResult,
  fitResultSucceeded,
  type LayoutFitResult,
  type LayoutFitTicket,
} from "./layoutFit";

const ITEM_CONTROLS: {
  field: keyof ItemStyle;
  title: string;
  min: number;
  max: number;
  step: number;
}[] = [
  { field: "font_size", title: "字号（磅）", min: 6, max: 72, step: 0.5 },
  { field: "space_before", title: "段前（磅）", min: 0, max: 48, step: 0.5 },
  { field: "space_after", title: "段后（磅）", min: 0, max: 48, step: 0.5 },
  { field: "line_spacing", title: "行距（倍）", min: 0.8, max: 3, step: 0.05 },
];

/** 保留数字输入过程，越界值不写入草稿，离开时恢复最后有效值 */
function ItemNumber({
  value,
  field,
  title,
  min,
  max,
  step,
  onChange,
}: {
  value?: number;
  field: keyof ItemStyle;
  title: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: number | undefined) => void;
}) {
  const [text, setText] = useState(value === undefined ? "" : String(value));
  useEffect(() => {
    setText(value === undefined ? "" : String(value));
  }, [value]);
  return (
    <input
      type="number"
      aria-label={`所选项${title}`}
      min={min}
      max={max}
      step={step}
      placeholder="沿用全局或模板"
      value={text}
      onChange={(event) => {
        const raw = event.target.value;
        setText(raw);
        const number = raw ? Number(raw) : undefined;
        if (number === undefined || validItemStyleNumber(field, number))
          onChange(number);
      }}
      onBlur={() => setText(value === undefined ? "" : String(value))}
    />
  );
}

/** 当前方案按文字项联动调整格式，自动压页使用实际 Word 分页 */
export default function LayoutSettings({
  document,
  resumeIdentity,
  previewInput,
  unavailable,
  onChange,
}: {
  document: ResumeDocument;
  resumeIdentity: string;
  previewInput: string | null;
  unavailable: boolean;
  onChange: (value: ResumeDocument) => void;
}) {
  const value = pageLayout(document);
  const input = previewInput
    ? (JSON.parse(previewInput) as { items: LayoutPreviewItem[] })
    : null;
  const items = layoutItems(document, input?.items ?? []);
  const [selectedKey, setSelectedKey] = useState("");
  const selected = items.find((item) => item.key === selectedKey) ?? items[0];
  const linked = selected ? itemLinked(value, selected) : true;
  const selectedStyle = selected ? declaredItemStyle(value, selected) : {};
  const [fitting, setFitting] = useState(false);
  const [message, setMessage] = useState("");
  const ticket = useRef<LayoutFitTicket | null>(null);
  const identity = JSON.stringify([resumeIdentity, previewInput, unavailable]);
  const latestIdentity = useRef(identity);
  const messageIdentity = useRef(identity);
  latestIdentity.current = identity;

  useEffect(() => {
    if (ticket.current && ticket.current.identity !== identity) {
      ticket.current.controller.abort();
      ticket.current = null;
      setFitting(false);
      setMessage("内容或版面已变化，已取消本次自动压页。");
    } else if (messageIdentity.current !== identity) setMessage("");
    messageIdentity.current = identity;
    return () => {
      ticket.current?.controller.abort();
    };
  }, [identity]);

  /** 手工调整回到基础样式，避免压缩系数再次改变输入的字号 */
  function changeLayout(next: PageLayout, manual = true) {
    setMessage("");
    if (ticket.current) {
      ticket.current.controller.abort();
      ticket.current = null;
      setFitting(false);
      setMessage("版面已变化，已取消本次自动压页。");
    }
    if (manual && value.auto_fit) {
      delete next.auto_fit;
      setMessage("已解除自动压页，按本次手工设置重新预览。");
    }
    const changed = withPageLayout(document, next);
    // 已采用结果对应的新输入可以继续展示实测消息，之后编辑时再清除
    messageIdentity.current = JSON.stringify([
      resumeIdentity,
      previewInput
        ? JSON.stringify({ ...JSON.parse(previewInput), document: changed })
        : null,
      unavailable,
    ]);
    onChange(changed);
  }

  /** 将全局选择写入方案草稿，真实 Word 预览自动更新 */
  function update(patch: Partial<PageLayout>) {
    changeLayout({ ...value, ...patch });
  }

  /** 立即作废请求身份，阻止取消后的响应写入草稿 */
  function cancelFit() {
    ticket.current?.controller.abort();
    ticket.current = null;
    setFitting(false);
    setMessage("已取消自动压页，保留当前版面。");
  }

  /** 冻结完整预览输入，在截止及身份校验通过后采用实测达标设置 */
  async function fitLayout() {
    if (!previewInput || unavailable) return;
    ticket.current?.controller.abort();
    const active = { identity, controller: new AbortController() };
    ticket.current = active;
    setFitting(true);
    setMessage("正在逐轮检查 Word 实际页数，请稍候…");
    const timeout = setTimeout(() => {
      if (!currentFitResult(active, ticket.current, latestIdentity.current))
        return;
      active.controller.abort();
      ticket.current = null;
      setFitting(false);
      setMessage("自动压页超时，保留当前版面，可稍后重试。");
    }, 210_000);
    try {
      const { api } = await import("@resume-maker/plugin-sdk/shared/lib/api");
      const result = await api<LayoutFitResult>(
        "/resume-previews/fit",
        "POST",
        JSON.parse(previewInput),
        active.controller.signal,
      );
      if (!currentFitResult(active, ticket.current, latestIdentity.current))
        return;
      ticket.current = null;
      setFitting(false);
      if (fitResultSucceeded(result, value.target_pages)) {
        if (result.status === "fit") changeLayout(result.options, false);
        setMessage(
          `${result.message} 实测 ${result.pages} 页，预算 ${value.target_pages} 页。`,
        );
      } else
        setMessage(
          result.message ||
            "当前内容无法在可读范围内压入预算页数，请精简内容或调整预算。",
        );
    } catch (error) {
      if (!currentFitResult(active, ticket.current, latestIdentity.current))
        return;
      ticket.current = null;
      setFitting(false);
      setMessage(
        error instanceof Error ? error.message : "自动压页失败，保留当前版面。",
      );
    } finally {
      clearTimeout(timeout);
    }
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
              changeLayout(
                { ...value, target_pages: Number(event.target.value) },
                false,
              )
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
        <label className="resume-layout-item-picker">
          调整文字项
          <select
            aria-label="调整文字项"
            value={selected?.key ?? ""}
            disabled={!items.length}
            onChange={(event) => setSelectedKey(event.target.value)}
          >
            {!items.length && <option value="">暂无可见文字</option>}
            {items.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {selected && (
          <>
            <button
              className="resume-layout-link"
              aria-label={linked ? "断开同类联动" : "恢复同类联动"}
              aria-pressed={linked}
              title={
                linked
                  ? "默认同类一起调整，点击后仅调整本项"
                  : "仅调整本项，点击后恢复同类样式"
              }
              onClick={() =>
                changeLayout(setItemLinked(value, selected, !linked))
              }
            >
              {linked ? <Link2 size={16} /> : <Unlink2 size={16} />}
              {linked
                ? `同类联动 · ${ITEM_TYPE_LABELS[selected.type]}`
                : "仅调整本项"}
            </button>
            {ITEM_CONTROLS.map(({ field, title, min, max, step }) => (
              <label key={field}>
                {title}
                <ItemNumber
                  key={`${selected.key}:${linked}`}
                  field={field}
                  title={title}
                  min={min}
                  max={max}
                  step={step}
                  value={selectedStyle[field]}
                  onChange={(number) => {
                    changeLayout(
                      updateItemStyle(value, selected, field, number),
                    );
                  }}
                />
              </label>
            ))}
          </>
        )}
        <div className="actions">
          <button
            disabled={!previewInput || unavailable}
            onClick={() => (fitting ? cancelFit() : void fitLayout())}
          >
            {fitting ? "取消自动压页" : "试用紧凑排版"}
          </button>
          <button onClick={() => changeLayout(resetPageLayout(value))}>
            恢复模板排版
          </button>
        </div>
        {message && <p role="status">{message}</p>}
        {value.auto_fit && (
          <p>已应用自动压页。上方显示基础设置，手工调整会解除本次自动压缩。</p>
        )}
        <p>
          链条连接时同类文字一起调整，断开后只改本项。清空数值可恢复继承。同一
          Word 段落内可分别设字号，段前、段后及行距取各项显式值的最大值。
        </p>
        <p>
          紧凑排版按实际 Word
          页数收紧间距、调整通用分页约束，再按统一比例缩字，最低 6
          磅；仍超预算时会明确提示。保存方案后保留设置。
        </p>
      </div>
    </details>
  );
}
