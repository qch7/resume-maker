import { Link2, Unlink2, X } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
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
  type LayoutPreviewItem,
} from "@resume-maker/plugin-sdk/shared/resume/itemLayout";
import LayoutItemPicker from "./LayoutItemPicker";
import LayoutNumber from "./LayoutNumber";
import { LayoutSelectionContext } from "./layoutSelection";
import {
  currentFitResult,
  fitResultSucceeded,
  type LayoutFitResult,
  type LayoutFitTicket,
} from "./layoutFit";

const ITEM_CONTROLS = {
  font_size: {
    title: "字号",
    unit: "磅",
    min: 6,
    max: 72,
    step: 0.5,
    fallback: 10.5,
    halfPoints: true,
  },
  line_spacing: {
    title: "行距",
    unit: "倍",
    min: 0.8,
    max: 3,
    step: 0.05,
    fallback: 1.2,
  },
  space_before: {
    title: "段前",
    unit: "磅",
    min: 0,
    max: 48,
    step: 0.5,
    fallback: 0,
  },
  space_after: {
    title: "段后",
    unit: "磅",
    min: 0,
    max: 48,
    step: 0.5,
    fallback: 3,
  },
};

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
  const selection = useContext(LayoutSelectionContext);
  const [localKey, setLocalKey] = useState("");
  const selectedKey = selection?.key ?? localKey;
  const selected = items.find((item) => item.key === selectedKey) ?? items[0];
  const [scope, setScope] = useState<"overall" | "items">(
    selection?.key ? "items" : "overall",
  );
  const [choosing, setChoosing] = useState(!selection?.key);
  const selectionExists = items.some((item) => item.key === selectedKey);
  const showPicker = choosing || !selectionExists;
  const panel = useRef<HTMLDetailsElement>(null);
  const linkedCount = selected
    ? items.filter(
        (item) => item.type === selected.type && itemLinked(value, item),
      ).length
    : 0;

  useEffect(() => {
    if (!selection?.request) return;
    setScope("items");
    setChoosing(false);
    if (panel.current) panel.current.open = true;
  }, [selection?.request]);

  useEffect(() => {
    /** 点击其他区域时收起设置，内容点选先交给共享选择处理 */
    function closeOutside(event: PointerEvent) {
      const target = event.target;
      if (
        target instanceof Element &&
        !panel.current?.contains(target) &&
        !target.closest(".content-layout-target") &&
        panel.current
      )
        panel.current.open = false;
    }
    window.document.addEventListener("pointerdown", closeOutside);
    return () =>
      window.document.removeEventListener("pointerdown", closeOutside);
  }, []);
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

  /** 关闭面板后将键盘焦点交回入口 */
  function closePanel() {
    if (panel.current) panel.current.open = false;
    panel.current?.querySelector("summary")?.focus();
  }

  /** 文字选择只改变当前工具目标，不写入简历或触发重新排版 */
  function selectItem(key: string) {
    setChoosing(false);
    if (selection) selection.select(key);
    else setLocalKey(key);
  }

  /** 逐项控件共用输入及继承规则 */
  function itemControl(field: keyof ItemStyle) {
    if (!selected) return null;
    const control = ITEM_CONTROLS[field];
    return (
      <LayoutNumber
        key={`${selected.key}:${linked}:${field}`}
        title={control.title}
        label={`所选项${control.title}（${control.unit}）`}
        unit={control.unit}
        value={selectedStyle[field]}
        options={control}
        onChange={(number) =>
          changeLayout(updateItemStyle(value, selected, field, number))
        }
      />
    );
  }

  return (
    <details
      ref={panel}
      className="resume-layout-settings"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        event.preventDefault();
        closePanel();
      }}
    >
      <summary>版面设置</summary>
      <div
        className="layout-settings-panel"
        role="group"
        aria-label="当前简历版面设置"
      >
        <div className="layout-settings-heading">
          <strong>调整排版</strong>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭版面设置"
            onClick={closePanel}
          >
            <X size={17} />
          </button>
        </div>
        <div className="layout-scope" role="group" aria-label="调整范围">
          <button
            type="button"
            aria-pressed={scope === "overall"}
            onClick={() => setScope("overall")}
          >
            整体排版
          </button>
          <button
            type="button"
            aria-pressed={scope === "items"}
            onClick={() => setScope("items")}
          >
            文字样式
          </button>
        </div>
        <div className="layout-settings-body">
          {scope === "overall" ? (
            <>
              <div className="layout-budget-row">
                <span>页数预算</span>
                <div
                  className="layout-page-budget"
                  role="group"
                  aria-label="页数预算"
                >
                  {[1, 2, 3].map((count) => (
                    <button
                      type="button"
                      key={count}
                      aria-pressed={value.target_pages === count}
                      onClick={() =>
                        changeLayout({ ...value, target_pages: count }, false)
                      }
                    >
                      {count} 页
                    </button>
                  ))}
                </div>
              </div>
              <LayoutNumber
                title="正文字号"
                unit="磅"
                value={value.font_size}
                options={{
                  min: 9,
                  max: 12,
                  step: 0.5,
                  fallback: 10.5,
                  halfPoints: true,
                }}
                onChange={(number) => update({ font_size: number })}
              />
              <LayoutNumber
                title="段落间距"
                unit="磅"
                value={value.space_after}
                options={{ min: 0, max: 8, step: 0.5, fallback: 3 }}
                onChange={(number) => update({ space_after: number })}
              />
              <LayoutNumber
                title="行距"
                unit="倍"
                value={value.line_spacing}
                options={{ min: 1, max: 1.5, step: 0.05, fallback: 1.2 }}
                onChange={(number) => update({ line_spacing: number })}
              />
              <p className="subtle">
                数值可直接输入，也可用 − / ＋
                微调。留空或点击重置图标可沿用模板。
              </p>
            </>
          ) : (
            <>
              {showPicker ? (
                <>
                  <div className="layout-picker-heading">
                    <span>选择要调整的文字</span>
                    {selectionExists && (
                      <button type="button" onClick={() => setChoosing(false)}>
                        返回调整
                      </button>
                    )}
                  </div>
                  <LayoutItemPicker
                    document={document}
                    items={items}
                    selectedKey={selected?.key ?? ""}
                    onSelect={selectItem}
                  />
                  <p className="subtle">
                    可搜索栏目、字段或内容；内容预览中也可直接点击文字。
                  </p>
                </>
              ) : (
                selected && (
                  <div className="layout-selected-controls">
                    <div className="layout-selected-heading">
                      <div
                        className="layout-selected-label"
                        title={selected.label}
                      >
                        <small>
                          正在调整 · {ITEM_TYPE_LABELS[selected.type]}
                        </small>
                        <strong>{selected.label}</strong>
                      </div>
                      <button
                        type="button"
                        className="layout-change-item"
                        onClick={() => setChoosing(true)}
                      >
                        更换文字
                      </button>
                    </div>
                    <button
                      type="button"
                      className="resume-layout-link"
                      aria-label={linked ? "断开同类联动" : "恢复同类联动"}
                      aria-pressed={linked}
                      title={linked ? "点击后仅调整本项" : "点击后恢复同类样式"}
                      onClick={() =>
                        changeLayout(setItemLinked(value, selected, !linked))
                      }
                    >
                      {linked ? <Link2 size={15} /> : <Unlink2 size={15} />}
                      {linked
                        ? `同类联动 · ${linkedCount} 项一起调整`
                        : "仅调整本项"}
                    </button>
                    {itemControl("font_size")}
                    {itemControl("line_spacing")}
                    <details className="layout-paragraph-controls">
                      <summary>段落间距</summary>
                      {itemControl("space_before")}
                      {itemControl("space_after")}
                      <p className="subtle">
                        同一 Word 段落的间距共用，取显式设置的最大值。
                      </p>
                    </details>
                  </div>
                )
              )}
            </>
          )}
        </div>
        <div className="layout-settings-footer">
          <div className="actions">
            <button
              type="button"
              disabled={!previewInput || unavailable}
              onClick={() => (fitting ? cancelFit() : void fitLayout())}
            >
              {fitting ? "取消自动压页" : "试用紧凑排版"}
            </button>
            <button
              type="button"
              onClick={() => changeLayout(resetPageLayout(value))}
            >
              恢复模板排版
            </button>
          </div>
          {message && <p role="status">{message}</p>}
          {value.auto_fit && (
            <p className="subtle">已启用自动压页；手工调整会解除本次压缩。</p>
          )}
        </div>
      </div>
    </details>
  );
}
