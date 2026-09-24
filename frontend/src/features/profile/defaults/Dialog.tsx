import { useEffect, useRef, useState } from "react";
import { Plus, Search, Trash2, X } from "lucide-react";
import type {
  DefaultField,
  DefaultSection,
  Experience,
  ResumeDefaults,
  ResumeDocument,
} from "../../../shared/types/index";
import { api } from "../../../shared/lib/api";
import { loadLocal, storage } from "../../../shared/lib/storage";
import { builtinDefaults, builtinFields, defaultHasContent } from "./model";
import DefaultDeleteDialog from "./DeleteDialog";
import {
  orderDefaultSections,
  searchDefaultFields,
  type DefaultSearchResult,
} from "./navigation";

/** 集中编辑默认栏目和条目字段，草稿恢复后仍由用户确认应用 */
export default function DefaultsDialog({
  initial,
  document,
  projects,
  onSave,
  onClose,
}: {
  initial?: ResumeDefaults | null;
  document: ResumeDocument | null;
  projects: Experience[];
  onSave: (value: ResumeDefaults) => Promise<void>;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const content = useRef<HTMLElement>(null);
  const navigation = useRef<HTMLElement>(null);
  const baseline = useRef("");
  const [value, setValue] = useState<ResumeDefaults>(
    /* 创建可取消的独立副本 */ () =>
      structuredClone(initial ?? builtinDefaults()),
  );
  const [deletion, setDeletion] = useState<{
    label: string;
    confirm: () => void;
  } | null>(null);
  const [selected, setSelected] = useState("personal");
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState<DefaultSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(
    /* 打开原生模态窗口并读取最新配置 */ () => {
      const element = dialog.current!;
      element.showModal();
      let active = true;
      void api<ResumeDefaults | null>("/settings/resume-defaults").then(
        /* 读取完成前禁止编辑以保证不会覆盖本地输入 */ (saved) => {
          if (active) {
            const current = saved ?? builtinDefaults();
            const ordered = {
              ...current,
              sections: orderDefaultSections(current.sections, document),
            };
            baseline.current = JSON.stringify(ordered);
            setValue(loadLocal("rm.settings.defaults", ordered));
            setLoading(false);
          }
        },
        /* 加载失败保留弹窗并阻止使用过期配置保存 */ (failure: Error) => {
          if (active) setError(failure.message);
        },
      );
      return /* 关闭组件后忽略在途响应 */ () => {
        active = false;
        element.close();
      };
    },
    [],
  );
  useEffect(
    /* 切换栏目后滚动到目标信息项并直接聚焦以便编辑 */ () => {
      if (!target) {
        if (content.current) content.current.scrollTop = 0;
      } else {
        const inputs = content.current?.querySelectorAll<HTMLInputElement>(
          "input[data-field-id]",
        );
        const input = target.fieldId
          ? [...(inputs ?? [])].find(
              /* 数据属性匹配避免特殊标识影响选择器 */ (item) =>
                item.dataset.fieldId === target.fieldId,
            )
          : content.current?.querySelector<HTMLInputElement>("input");
        input?.scrollIntoView({ block: "center" });
        input?.focus({ preventScroll: true });
        input?.select();
      }
      if (!query)
        navigation.current
          ?.querySelector(".active")
          ?.scrollIntoView({ block: "nearest" });
    },
    [selected, target, query],
  );
  const orderedSections = orderDefaultSections(value.sections);
  useEffect(() => {
    if (!loading) {
      if (JSON.stringify(value) === baseline.current)
        storage.removeItem("rm.settings.defaults");
      else storage.setItem("rm.settings.defaults", JSON.stringify(value));
    }
  }, [value, loading]);
  const results = searchDefaultFields(value, query);
  const searching = !!query.trim();
  const section = value.sections.find(
    /* 个人信息始终固定在首项 */ (item) => item.id === selected,
  );
  const fields = section?.fields ?? value.personal_fields;
  const locked = busy || loading;
  const builtins = builtinFields(section);
  const missing = builtins.filter(
    /* 按字段标识恢复已删除的内置项 */ (field) =>
      !fields.some(/* 比较字段标识 */ (item) => item.id === field.id),
  );
  /** 普通导航从栏目顶部开始，清除上一次搜索定位 */
  function selectSection(id: string) {
    setSelected(id);
    setTarget(null);
    setQuery("");
  }
  /** 搜索结果恢复完整导航并定位，重复选择同一项也会重新滚动 */
  function jumpTo(result: DefaultSearchResult) {
    setSelected(result.sectionId);
    setTarget({ ...result });
    setQuery("");
  }
  /** 更新选中栏目，其他栏目和个人信息保持不变 */
  function updateSection(patch: Partial<DefaultSection>) {
    setValue({
      ...value,
      sections: value.sections.map(
        /* 只更新当前栏目 */ (item) =>
          item.id === selected ? { ...item, ...patch } : item,
      ),
    });
  }
  /** 更新当前字段组，名称和初始显隐共同保存 */
  function updateFields(next: DefaultField[]) {
    if (section) updateSection({ fields: next });
    else setValue({ ...value, personal_fields: next });
  }
  /** 新增默认栏目使用稳定标识，后续新简历复用其结构 */
  function addSection() {
    const item: DefaultSection = {
      id: `section:${crypto.randomUUID()}`,
      title: "新栏目",
      kind: "text",
      parent_id: null,
      visible: true,
      fields: structuredClone(
        builtinFields({ id: "", title: "", kind: "text" }),
      ),
    };
    setValue({ ...value, sections: [...value.sections, item] });
    selectSection(item.id);
  }
  /** 删除默认栏目时将子栏目提升，当前简历内容由应用逻辑保留 */
  function removeSection() {
    setValue({
      ...value,
      sections: value.sections
        .filter(
          /* 项目区保持独立入口 */ (item) =>
            item.id !== selected || item.kind === "projects",
        )
        .map(
          /* 保留子栏目并解除父级引用 */ (item) =>
            item.parent_id === selected ? { ...item, parent_id: null } : item,
        ),
    });
    selectSection("personal");
  }
  /** 保存失败时保留编辑副本，便于修正或重试 */
  function requestDelete(label: string, confirm: () => void, fieldId?: string) {
    if (defaultHasContent(document, selected, fieldId, projects, section))
      setDeletion({ label, confirm });
    else confirm();
  }
  /** 保存失败时保留编辑副本，便于修正或重试 */
  async function save() {
    setBusy(true);
    setError("");
    try {
      await onSave({ ...value, sections: orderedSections });
      storage.removeItem("rm.settings.defaults");
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }
  /** 用户明确取消时清除本份草稿，意外刷新仍可恢复输入 */
  function close() {
    if (busy) return;
    if (
      !loading &&
      JSON.stringify(value) !== baseline.current &&
      !window.confirm("有尚未保存的栏目设置，确定放弃修改吗？")
    )
      return;
    storage.removeItem("rm.settings.defaults");
    onClose();
  }
  return (
    <>
      <dialog
        ref={dialog}
        className="defaults-dialog"
        aria-labelledby="defaults-title"
        onCancel={
          /* 保存完成前保持窗口打开 */ (event) => {
            event.preventDefault();
            close();
          }
        }
      >
        <header className="defaults-header">
          <h2 id="defaults-title">默认栏目设置</h2>
          <div className="defaults-search">
            <Search size={14} aria-hidden="true" />
            <input
              aria-label="搜索栏目或信息项"
              placeholder="搜索栏目或信息项"
              value={query}
              disabled={locked}
              onChange={
                /* 按搜索词筛选导航 */ (event) => {
                  setTarget(null);
                  setQuery(event.target.value);
                }
              }
              onKeyDown={
                /* 回车跳到首个结果，中文输入法确认文字时不跳转 */ (event) => {
                  if (
                    event.key === "Enter" &&
                    !event.nativeEvent.isComposing &&
                    results[0]
                  ) {
                    event.preventDefault();
                    jumpTo(results[0]);
                  }
                }
              }
            />
            {query && (
              <button
                className="icon-button"
                aria-label="清除搜索"
                onClick={/* 恢复完整栏目列表 */ () => setQuery("")}
              >
                <X size={14} />
              </button>
            )}
          </div>
          <button
            className="icon-button"
            aria-label="关闭默认栏目设置"
            disabled={busy}
            onClick={close}
          >
            <X size={18} />
          </button>
        </header>
        <div className="defaults-layout" aria-busy={locked}>
          <nav ref={navigation} className="defaults-nav" aria-label="默认栏目">
            {searching ? (
              <>
                <span className="defaults-search-count" role="status">
                  {results.length ? `${results.length} 项匹配` : "无匹配结果"}
                </span>
                {results.map(
                  /* 同名信息项显示所属栏目，点击精确定位 */ (result) => (
                    <button
                      key={`${result.sectionId}/${result.fieldId ?? ""}`}
                      className="defaults-search-result"
                      disabled={locked}
                      onClick={
                        /* 切换栏目并滚动到对应输入框 */ () => jumpTo(result)
                      }
                    >
                      <span>{result.title}</span>
                      {result.fieldId && <small>{result.sectionTitle}</small>}
                    </button>
                  ),
                )}
              </>
            ) : (
              <>
                <button
                  className={selected === "personal" ? "active" : ""}
                  disabled={locked}
                  onClick={
                    /* 切换到固定顶部个人信息 */ () => selectSection("personal")
                  }
                >
                  个人信息
                </button>
                {orderedSections.map(
                  /* 子栏目使用缩进呈现其归属 */ (item) => (
                    <button
                      key={item.id}
                      className={selected === item.id ? "active" : ""}
                      data-child={!!item.parent_id}
                      disabled={locked}
                      onClick={
                        /* 切换当前编辑的字段组 */ () => selectSection(item.id)
                      }
                    >
                      {item.parent_id ? "↳ " : ""}
                      {item.title || "未命名栏目"}
                    </button>
                  ),
                )}
                <button
                  disabled={locked || value.sections.length >= 40}
                  onClick={addSection}
                >
                  <Plus size={14} />
                  添加默认栏目
                </button>
              </>
            )}
          </nav>
          <section
            ref={content}
            className="defaults-content"
            aria-label="默认字段编辑"
          >
            {section && (
              <div className="defaults-section-settings">
                <label>
                  栏目名称
                  <input
                    value={section.title}
                    maxLength={100}
                    disabled={locked}
                    onChange={
                      /* 改名不改变栏目身份 */ (event) =>
                        updateSection({ title: event.target.value })
                    }
                  />
                </label>
                <label>
                  内容类型
                  <select
                    value={section.kind}
                    disabled={locked || section.kind === "projects"}
                    onChange={
                      /* 更改布局保留已有字段定义 */ (event) =>
                        updateSection({
                          kind: event.target.value as "education" | "text",
                        })
                    }
                  >
                    <option value="text">通用资料</option>
                    <option value="education">教育经历</option>
                    {section.kind === "projects" && (
                      <option value="projects">项目经历</option>
                    )}
                  </select>
                </label>
                <label>
                  所属栏目
                  <select
                    value={section.parent_id ?? ""}
                    disabled={
                      locked ||
                      section.kind === "projects" ||
                      value.sections.some(
                        /* 有子栏目的栏目不能再归入其他栏目 */ (item) =>
                          item.parent_id === section.id,
                      )
                    }
                    onChange={
                      /* 限制为大栏目加子栏目两层 */ (event) =>
                        updateSection({ parent_id: event.target.value || null })
                    }
                  >
                    <option value="">独立大栏目</option>
                    {orderedSections
                      .filter(
                        /* 排除自己和其他子栏目 */ (item) =>
                          item.id !== section.id && !item.parent_id,
                      )
                      .map(
                        /* 父栏目使用稳定标识 */ (item) => (
                          <option key={item.id} value={item.id}>
                            {item.title}
                          </option>
                        ),
                      )}
                  </select>
                </label>
                <div className="defaults-section-actions">
                  <label className="defaults-check">
                    <input
                      type="checkbox"
                      checked={section.visible}
                      disabled={locked}
                      onChange={
                        /* 新简历采用该初始显隐 */ (event) =>
                          updateSection({ visible: event.target.checked })
                      }
                    />
                    默认显示栏目
                  </label>
                  <button
                    className="text-button danger-hover"
                    disabled={locked || section.kind === "projects"}
                    onClick={
                      /* 删除有正文的默认栏目也需要确认 */ () =>
                        requestDelete(section.title, removeSection)
                    }
                  >
                    <Trash2 size={14} />
                    删除默认栏目
                  </button>
                </div>
              </div>
            )}
            <div className="defaults-field-head">
              <span>信息项名称</span>
              <span>默认显示</span>
              <span />
            </div>
            {fields.map(
              /* 默认字段和自定义默认项使用相同编辑方式 */ (field, index) => (
                <div
                  className="defaults-field-row"
                  data-search-target={
                    target?.sectionId === selected &&
                    target.fieldId === field.id
                  }
                  key={field.id}
                >
                  <input
                    data-field-id={field.id}
                    aria-label={`默认项 ${index + 1} 名称`}
                    value={field.label}
                    maxLength={50}
                    disabled={locked}
                    placeholder="信息项名称"
                    onChange={
                      /* 只改标签，既有内容仍按原标识匹配 */ (event) =>
                        updateFields(
                          fields.map(
                            /* 更新单个字段名称 */ (item) =>
                              item.id === field.id
                                ? { ...item, label: event.target.value }
                                : item,
                          ),
                        )
                    }
                  />
                  <input
                    type="checkbox"
                    aria-label={`${field.label || "未命名项"}默认显示`}
                    checked={field.visible}
                    disabled={locked}
                    onChange={
                      /* 设置初始显隐 */ (event) =>
                        updateFields(
                          fields.map(
                            /* 更新单个字段显隐 */ (item) =>
                              item.id === field.id
                                ? { ...item, visible: event.target.checked }
                                : item,
                          ),
                        )
                    }
                  />
                  <button
                    className="icon-button danger-hover"
                    aria-label={`删除默认项${field.label}`}
                    disabled={locked}
                    onClick={
                      /* 从定义中删除，当前资料值在应用时归档隐藏 */ () =>
                        requestDelete(
                          field.label,
                          /* 确认后只移除当前定义 */ () =>
                            updateFields(
                              fields.filter(
                                /* 保留其他字段 */ (item) =>
                                  item.id !== field.id,
                              ),
                            ),
                          field.id,
                        )
                    }
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ),
            )}
            {!fields.length && <p className="subtle">暂无默认项</p>}
            <div className="defaults-add-fields">
              <button
                disabled={
                  locked ||
                  fields.filter(
                    /* 仅统计自定义默认项 */ (field) =>
                      field.id.startsWith("default:"),
                  ).length >= 20
                }
                onClick={
                  /* 新默认项的稳定标识用于跨简历复用 */ () =>
                    updateFields([
                      ...fields,
                      {
                        id: `default:${crypto.randomUUID()}`,
                        label: "新信息项",
                        visible: true,
                      },
                    ])
                }
              >
                <Plus size={14} />
                添加默认项
              </button>
              {!!missing.length && (
                <select
                  aria-label="恢复内置项"
                  value=""
                  disabled={locked}
                  onChange={
                    /* 恢复内置字段，可重新显示保留的原始值 */ (event) => {
                      const field = missing.find(
                        /* 查找所选内置定义 */ (item) =>
                          item.id === event.target.value,
                      );
                      if (field) updateFields([...fields, { ...field }]);
                    }
                  }
                >
                  <option value="">恢复内置项…</option>
                  {missing.map(
                    /* 列出尚未启用的内置项 */ (field) => (
                      <option key={field.id} value={field.id}>
                        {field.label}
                      </option>
                    ),
                  )}
                </select>
              )}
            </div>
          </section>
        </div>
        <footer className="defaults-footer">
          {error ? (
            <p className="warning" role="alert">
              {error}
            </p>
          ) : (
            loading && (
              <p className="subtle" role="status">
                正在读取…
              </p>
            )
          )}
          <div className="actions">
            <button disabled={busy} onClick={close}>
              取消
            </button>
            <button
              className="primary"
              disabled={
                locked ||
                !value.sections.every(
                  /* 禁止保存空白栏目名 */ (item) => item.title.trim(),
                ) ||
                ![
                  value.personal_fields,
                  ...value.sections.map(
                    /* 汇总各组字段 */ (item) => item.fields,
                  ),
                ]
                  .flat()
                  .every(/* 默认项必须有名称 */ (field) => field.label.trim())
              }
              onClick={save}
            >
              {busy ? "保存中…" : "保存设置"}
            </button>
          </div>
        </footer>
      </dialog>
      {deletion && (
        <DefaultDeleteDialog
          label={deletion.label}
          onClose={/* 取消删除保留所有定义 */ () => setDeletion(null)}
          onConfirm={
            /* 确认删除并返回设置表单 */ () => {
              deletion.confirm();
              setDeletion(null);
            }
          }
        />
      )}
    </>
  );
}
