import {
  ChevronRight,
  Folder,
  FolderOpen,
  FolderPlus,
  Heart,
  LayoutGrid,
  List,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../lib/api";
import type { Template } from "../../types";
import TemplateEntries from "./TemplateEntries";
import Thumbnail from "./Thumbnail";
import {
  filterTemplates,
  libraryTemplates,
  templateDate,
  type LibraryState,
  type LibraryTemplate,
} from "./library";

/** 读取上次视图偏好，浏览器禁止本地存储时仍默认展示卡片。 */
function initialView(): "cards" | "list" {
  try {
    return localStorage.getItem("rm.template.library.view") === "list"
      ? "list"
      : "cards";
  } catch {
    return "cards";
  }
}

/** 以原生模态层提供资源管理器布局，焦点和 Escape 不会穿透至父工作区。 */
export default function LibraryDialog({
  templates,
  value,
  onClose,
  onChange,
}: {
  templates: Template[];
  value: string;
  onClose: () => void;
  onChange: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const [library, setLibrary] = useState<LibraryState>({
    categories: [],
    items: {},
  });
  const [loaded, setLoaded] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [folder, setFolder] = useState("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("name");
  const [view, setView] = useState(initialView);
  const [selectedId, setSelectedId] = useState(value || "builtin");
  const [adding, setAdding] = useState(false);
  const [categoryDraft, setCategoryDraft] = useState("");
  const items = libraryTemplates(templates, library);
  const visible = filterTemplates(items, folder, query, sort);
  const selected = visible.find(
    /* 仅可确认当前结果中可见的模板。 */ (item) => item.id === selectedId,
  );
  const category = library.categories.find(
    /* 定位可管理的自定义分类。 */ (item) => item.id === folder,
  );

  useEffect(
    /* 原生弹窗处理焦点约束与关闭后的焦点恢复。 */ () => {
      alive.current = true;
      const element = dialog.current!;
      element.showModal();
      search.current?.focus();
      return /* 先关闭模态层，再回收组件。 */ () => {
        alive.current = false;
        element.close();
      };
    },
    [],
  );
  useEffect(
    /* 每次打开重新读取数据库，让两个入口共享最新收藏与分类。 */ () => {
      const controller = new AbortController();
      setLoaded(false);
      setError("");
      void api<LibraryState>(
        "/template-library",
        "GET",
        undefined,
        controller.signal,
      )
        .then(
          /* 仅发布仍属于当前弹窗的读取结果。 */ (state) => {
            if (!controller.signal.aborted) {
              setLibrary(state);
              setLoaded(true);
            }
          },
        )
        .catch(
          /* 网络异常不清空数据库里的组织信息。 */ (reason: Error) => {
            if (!controller.signal.aborted) setError(reason.message);
          },
        );
      return /* 关闭或重新加载时取消旧请求。 */ () => controller.abort();
    },
    [reload],
  );

  /** 统一保存状态与错误提示，等待成功后更新分类和 Like。 */
  async function save(path: string, method: string, body?: unknown) {
    setPending(true);
    setError("");
    try {
      const state = await api<LibraryState>(
        `/template-library${path}`,
        method,
        body,
      );
      if (alive.current) setLibrary(state);
      return state;
    } catch (reason) {
      if (alive.current) setError((reason as Error).message);
      return null;
    } finally {
      if (alive.current) setPending(false);
    }
  }
  /** 空标识即未分类，内置模板与导入模板使用相同分类规则。 */
  function categoryName(id: string) {
    return (
      library.categories.find(
        /* 查找自定义分类名称。 */ (item) => item.id === id,
      )?.name ?? "未分类"
    );
  }
  /** 确认当前有效模板，取消或单击浏览不会触发此回调。 */
  function confirm(id: string) {
    onChange(id === "builtin" ? "" : id);
    onClose();
  }
  /** 切换视图后保留分类、搜索与选中项，并记住偏好。 */
  function changeView(next: "cards" | "list") {
    setView(next);
    try {
      localStorage.setItem("rm.template.library.view", next);
    } catch {
      /* 存储不可用时保留本次偏好。 */
    }
  }
  /** 点击侧栏清除旧搜索，让新分类的内容完整显示。 */
  function openFolder(id: string) {
    setFolder(id);
    setQuery("");
  }
  /** 新建成功后进入分类，可从全部模板中把模板移入该分类。 */
  async function createCategory() {
    const state = await save("/categories", "POST", { name: categoryDraft });
    if (state && alive.current) {
      setAdding(false);
      setCategoryDraft("");
      openFolder(state.categories.at(-1)!.id);
    }
  }
  /** 仅合并 Like 字段，不覆盖模板分类。 */
  function like(item: LibraryTemplate) {
    void save(`/items/${encodeURIComponent(item.id)}`, "PATCH", {
      liked: !item.liked,
    });
  }
  const folderName =
    folder === "all"
      ? "全部模板"
      : folder === "liked"
        ? "我的喜欢"
        : categoryName(folder);
  const folders = [
    { id: "all", name: "全部模板", count: items.length, icon: FolderOpen },
    {
      id: "liked",
      name: "我的喜欢",
      count: items.filter(/* 统计跨分类的收藏总数。 */ (item) => item.liked)
        .length,
      icon: Heart,
    },
    {
      id: "",
      name: "未分类",
      count: items.filter(
        /* 尚未分类的模板独立计数。 */ (item) => !item.category_id,
      ).length,
      icon: Folder,
    },
    ...library.categories.map(
      /* 自定义分类显示各自模板数。 */ (entry) => ({
        ...entry,
        count: items.filter(
          /* 按分类标识统计模板。 */ (item) => item.category_id === entry.id,
        ).length,
        icon: Folder,
      }),
    ),
  ];

  return createPortal(
    <dialog
      ref={dialog}
      className="template-library-dialog"
      aria-labelledby="template-library-title"
      onCancel={onClose}
    >
      <header className="library-titlebar">
        <div>
          <FolderOpen size={21} />
          <h2 id="template-library-title">模板库</h2>
          <span>找到适合你的下一份简历</span>
        </div>
        <button
          className="icon-button"
          aria-label="关闭模板库"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </header>
      <div className="library-toolbar">
        <div className="library-address">
          <FolderOpen size={16} />
          <button onClick={/* 面包屑返回全部模板。 */ () => openFolder("all")}>
            模板库
          </button>
          <ChevronRight size={14} />
          <strong>{folderName}</strong>
        </div>
        <div className="library-search">
          <Search size={16} />
          <input
            ref={search}
            autoFocus
            aria-label="搜索模板"
            placeholder={`搜索${folderName}`}
            value={query}
            onChange={
              /* 即时筛选当前分类名称。 */ (event) =>
                setQuery(event.target.value)
            }
          />
          {query && (
            <button
              className="icon-button"
              aria-label="清除搜索"
              onClick={/* 恢复当前分类的全部模板。 */ () => setQuery("")}
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>
      <div className="library-body">
        <nav className="library-sidebar" aria-label="模板分类">
          <span className="library-sidebar-caption">模板位置</span>
          {folders.map(
            /* 分类导航不受搜索结果数量影响。 */ (entry, index) => (
              <button
                key={entry.id}
                className={`${folder === entry.id ? "active" : ""} ${index === 2 ? "library-category-start" : ""}`}
                aria-current={folder === entry.id ? "page" : undefined}
                onClick={/* 打开侧栏分类。 */ () => openFolder(entry.id)}
              >
                <entry.icon size={17} />
                <span>{entry.name}</span>
                <small>{entry.count}</small>
              </button>
            ),
          )}
          {adding ? (
            <form
              className="library-category-form"
              onSubmit={
                /* 提交名称，不触发页面导航。 */ (event) => {
                  event.preventDefault();
                  void createCategory();
                }
              }
            >
              <input
                autoFocus
                aria-label="新分类名称"
                placeholder="分类名称"
                maxLength={50}
                value={categoryDraft}
                disabled={pending}
                onChange={
                  /* 保存尚未提交的分类名称。 */ (event) =>
                    setCategoryDraft(event.target.value)
                }
              />
              <div>
                <button
                  type="submit"
                  disabled={pending || !categoryDraft.trim()}
                >
                  创建
                </button>
                <button
                  type="button"
                  disabled={pending}
                  onClick={/* 放弃尚未创建的分类。 */ () => setAdding(false)}
                >
                  取消
                </button>
              </div>
            </form>
          ) : (
            <button
              className="library-add-category"
              disabled={!loaded || pending}
              onClick={
                /* 在侧栏内创建分类，无需离开选择流程。 */ () => setAdding(true)
              }
            >
              <FolderPlus size={17} />
              新建分类
            </button>
          )}
        </nav>
        <main className="library-main">
          <div className="library-content-toolbar">
            <div>
              <h3>{folderName}</h3>
              <span>{visible.length} 个模板</span>
            </div>
            <div className="library-view-controls">
              {category && (
                <button
                  className="icon-button"
                  disabled={pending || !loaded}
                  aria-label={`删除分类 ${category.name}`}
                  title="删除分类，模板将回到未分类"
                  onClick={
                    /* 删除只解除分类，不删除模板。 */ async () => {
                      if (await save(`/categories/${category.id}`, "DELETE"))
                        openFolder("");
                    }
                  }
                >
                  <Trash2 size={16} />
                </button>
              )}
              <select
                aria-label="模板排序"
                value={sort}
                onChange={
                  /* 两种视图使用相同的排序方式。 */ (event) =>
                    setSort(event.target.value)
                }
              >
                <option value="name">名称排序</option>
                <option value="newest">最近保存</option>
              </select>
              <div
                className="library-view-toggle"
                role="group"
                aria-label="模板展示方式"
              >
                <button
                  aria-label="卡片展示"
                  aria-pressed={view === "cards"}
                  onClick={/* 切换到真实预览卡片。 */ () => changeView("cards")}
                >
                  <LayoutGrid size={17} />
                </button>
                <button
                  aria-label="列表展示"
                  aria-pressed={view === "list"}
                  onClick={/* 切换到紧凑文件列表。 */ () => changeView("list")}
                >
                  <List size={17} />
                </button>
              </div>
            </div>
          </div>
          {error && (
            <div className="library-error" role="alert">
              <span>{error}</span>
              {!loaded && (
                <button
                  onClick={
                    /* 重新读取失败的组织信息。 */ () => setReload(reload + 1)
                  }
                >
                  重试
                </button>
              )}
            </div>
          )}
          <div className="library-scroll" aria-busy={pending || !loaded}>
            {!loaded ? (
              <div className="library-empty">
                <FolderOpen size={36} />
                <h3>{error ? "模板库暂时无法加载" : "正在打开模板库…"}</h3>
              </div>
            ) : visible.length ? (
              <TemplateEntries
                items={visible}
                view={view}
                selected={selectedId}
                current={value || "builtin"}
                categoryName={categoryName}
                pending={pending}
                onSelect={setSelectedId}
                onConfirm={confirm}
                onLike={like}
              />
            ) : (
              <div className="library-empty">
                {folder === "liked" ? (
                  <Heart size={36} />
                ) : (
                  <FolderOpen size={36} />
                )}
                <h3>
                  {query
                    ? "没有找到匹配的模板"
                    : folder === "liked"
                      ? "还没有喜欢的模板"
                      : "这个分类还没有模板"}
                </h3>
                <p>
                  {query
                    ? "试试其他名称，或清除搜索。"
                    : folder === "liked"
                      ? "点击模板旁的爱心，就能在这里快速找到它。"
                      : "在全部模板中选中模板，再修改右侧的所属分类。"}
                </p>
                <button
                  onClick={
                    /* 空搜索清除关键词，空分类返回全部模板。 */ () =>
                      query ? setQuery("") : openFolder("all")
                  }
                >
                  {query ? "清除搜索" : "浏览全部模板"}
                </button>
              </div>
            )}
          </div>
        </main>
        <aside className="library-details" aria-label="所选模板详情">
          {selected && loaded ? (
            <>
              <div className="library-detail-preview">
                <Thumbnail
                  key={selected.id}
                  id={selected.id}
                  name={selected.name}
                />
              </div>
              <h3>{selected.name}</h3>
              <p>
                {selected.id === "builtin"
                  ? "内置版式 · 示例内容"
                  : "Word 模板 · 原文首页"}
              </p>
              <dl>
                <dt>保存日期</dt>
                <dd>{templateDate(selected.created_at)}</dd>
              </dl>
              <label>
                所属分类
                <select
                  aria-label="所选模板分类"
                  disabled={pending}
                  value={selected.category_id}
                  onChange={
                    /* 分类修改立即持久化，不改变当前简历。 */ (event) =>
                      void save(
                        `/items/${encodeURIComponent(selected.id)}`,
                        "PATCH",
                        { category_id: event.target.value },
                      )
                  }
                >
                  <option value="">未分类</option>
                  {library.categories.map(
                    /* 提供全部已创建的目标分类。 */ (entry) => (
                      <option key={entry.id} value={entry.id}>
                        {entry.name}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <button
                className={`library-detail-like ${selected.liked ? "is-liked" : ""}`}
                aria-pressed={selected.liked}
                disabled={pending}
                onClick={
                  /* 详情面板与卡片共用同一个 Like 状态。 */ () =>
                    like(selected)
                }
              >
                <Heart
                  size={16}
                  fill={selected.liked ? "currentColor" : "none"}
                />
                {selected.liked ? "已喜欢 · Like" : "喜欢这个模板 · Like"}
              </button>
              <p className="library-detail-hint">
                选择模板后，可继续用当前资料试填和调整。
              </p>
            </>
          ) : (
            <div className="library-detail-empty">
              <FilePlaceholder />
              <span>选中模板查看详情</span>
            </div>
          )}
        </aside>
      </div>
      <footer className="library-footer">
        <div>
          <span>{visible.length} 个模板</span>
          <span className="library-footer-selection">
            {selected && loaded ? `已选：${selected.name}` : "请选择一个模板"}
          </span>
        </div>
        <div>
          <button onClick={onClose}>取消</button>
          <button
            className="primary"
            disabled={!selected || !loaded || pending}
            onClick={
              /* 确认后返回发起选择的工作区。 */ () =>
                selected && confirm(selected.id)
            }
          >
            选择模板
          </button>
        </div>
      </footer>
    </dialog>,
    document.body,
  );
}

/** 详情空态使用轻量文件夹图标。 */
function FilePlaceholder() {
  return <FolderOpen size={30} strokeWidth={1.3} />;
}
