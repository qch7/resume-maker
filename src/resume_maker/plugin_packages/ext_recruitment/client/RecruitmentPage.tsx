import { useEffect, useRef, useState } from "react";
import {
  Bookmark as BookmarkIcon,
  Download,
  FolderOpen,
  Globe,
  LayoutGrid,
  List,
  Plus,
  RefreshCw,
  Search,
  Star,
  Upload,
} from "lucide-react";
import { api, download } from "@resume-maker/plugin-sdk/shared/lib/api";
import {
  loadLocal,
  storage,
} from "@resume-maker/plugin-sdk/shared/lib/storage";
import BookmarkEditor from "./BookmarkEditor";
import BookmarkCard from "./BookmarkCard";
import GroupsEditor from "./GroupsEditor";
import ImportDialog from "./ImportDialog";
import Dialog from "./Dialog";
import {
  filterBookmarks,
  newBookmark,
  scopeCategories,
  sortBookmarks,
  restoreDisplayPreferences,
  type BookmarkSort,
  type Bookmark,
  type BookmarkFile,
  type Snapshot,
} from "./model";

/** 按用户创建或导入的领域和分类组织招聘网址 */
export default function RecruitmentPage({ active }: { active: boolean }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [domain, setDomain] = useState("");
  const [category, setCategory] = useState("");
  const [favorites, setFavorites] = useState(false);
  const [query, setQuery] = useState("");
  const [display, setDisplay] = useState(() =>
    restoreDisplayPreferences(loadLocal("rm.recruitment.display", {})),
  );
  useEffect(() => {
    storage.setItem("rm.recruitment.display", JSON.stringify(display));
  }, [display]);
  const [editing, setEditing] = useState<Bookmark | null>(null);
  const [groupsOpen, setGroupsOpen] = useState<"domains" | "categories" | null>(
    null,
  );
  const [importing, setImporting] = useState(false);
  const [deleting, setDeleting] = useState<Bookmark | null>(null);
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const readGeneration = useRef(0);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const data = snapshot?.data;
  const items = data?.bookmarks ?? [];
  const categories = scopeCategories(
    data?.categories ?? [],
    items,
    domain,
    favorites,
  );
  const selectedCategory = categories.some((item) => item.id === category)
    ? category
    : "";
  useEffect(() => {
    if (!active || locked.current) return;
    const generation = ++readGeneration.current;
    const controller = new AbortController();
    void api<Snapshot>("/recruitment", "GET", undefined, controller.signal)
      .then((value) => {
        if (
          !controller.signal.aborted &&
          generation === readGeneration.current
        ) {
          setSnapshot(value);
          setError("");
        }
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted && generation === readGeneration.current)
          setError(failure.message);
      });
    return () => controller.abort();
  }, [active]);
  useEffect(() => {
    if (
      snapshot &&
      domain &&
      !snapshot.data.domains.some((item) => item.id === domain)
    )
      setDomain("");
  }, [snapshot, domain]);
  useEffect(() => {
    if (category !== selectedCategory) setCategory(selectedCategory);
  }, [category, selectedCategory]);
  /** 刷新服务器版本，供并发冲突恢复和用户主动同步 */
  async function refresh() {
    if (locked.current) throw new Error("另一个操作仍在处理中，请稍后重试。");
    locked.current = true;
    setBusy(true);
    const generation = ++readGeneration.current;
    try {
      const value = await api<Snapshot>("/recruitment");
      if (generation === readGeneration.current) {
        setSnapshot(value);
        setError("");
      }
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  /** 串行提交完整收藏夹，失败保留现有列表及独立编辑表单 */
  async function save(data: BookmarkFile) {
    if (!snapshot || locked.current)
      throw new Error("另一个操作仍在保存，请稍后重试。");
    locked.current = true;
    ++readGeneration.current;
    setBusy(true);
    try {
      const saved = await api<Snapshot>("/recruitment", "PUT", {
        revision: snapshot.revision,
        data,
      });
      setSnapshot(saved);
      setError("");
      setMessage("");
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  /** 处理列表操作的异常，表单操作则由各自窗口显示错误 */
  async function perform(action: () => Promise<void>) {
    setError("");
    setMessage("");
    try {
      await action();
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  /** 保存一个条目，其他领域和收藏均保留最新列表内容 */
  async function saveItem(item: Bookmark) {
    if (!snapshot) return;
    const exists = snapshot.data.bookmarks.some(
      (entry) => entry.id === item.id,
    );
    await save({
      ...snapshot.data,
      bookmarks: exists
        ? snapshot.data.bookmarks.map((entry) =>
            entry.id === item.id ? item : entry,
          )
        : [...snapshot.data.bookmarks, item],
    });
  }
  /** 创建收藏时优先使用当前筛选领域和分类 */
  function add() {
    if (!snapshot) return;
    const item = newBookmark(domain);
    item.category = selectedCategory;
    setEditing(item);
  }
  const filtered = sortBookmarks(
    filterBookmarks(items, domain, selectedCategory, favorites, query),
    display.sort,
  );
  const scoped = filterBookmarks(items, domain, "", favorites, query);
  return (
    <section
      className="recruitment-page"
      hidden={!active}
      aria-label="招聘收藏夹"
    >
      <header className="recruitment-heading">
        <h1>招聘收藏夹</h1>
        <div className="actions">
          <button disabled={!data || busy} onClick={() => setImporting(true)}>
            <Upload size={16} />
            导入
          </button>
          <button
            disabled={!data || busy}
            onClick={() =>
              void perform(() =>
                download("/recruitment/export", "recruitment.bookmarks.json"),
              )
            }
          >
            <Download size={16} />
            导出全部
          </button>
          <button className="primary" disabled={!data || busy} onClick={add}>
            <Plus size={17} />
            添加收藏
          </button>
        </div>
      </header>
      <div className="recruitment-body">
        <aside className="recruitment-sidebar" aria-label="收藏夹领域">
          <button
            className={!favorites && !domain ? "selected" : ""}
            onClick={() => {
              setDomain("");
              setFavorites(false);
            }}
          >
            <Globe size={17} />
            全部网站<span>{items.length}</span>
          </button>
          <button
            className={favorites ? "selected" : ""}
            onClick={() => {
              setDomain("");
              setFavorites(true);
            }}
          >
            <Star size={17} />
            星标<span>{items.filter((item) => item.favorite).length}</span>
          </button>
          <div className="recruitment-sidebar-heading">
            <b>领域</b>
            <button
              disabled={!data || busy}
              className="text-button"
              onClick={() => setGroupsOpen("domains")}
            >
              管理
            </button>
          </div>
          {data?.domains.map((entry) => (
            <button
              key={entry.id}
              className={domain === entry.id ? "selected" : ""}
              onClick={() => {
                setDomain(entry.id);
                setFavorites(false);
              }}
            >
              <FolderOpen size={16} />
              <strong>{entry.name}</strong>
              <span>
                {items.filter((item) => item.domain_id === entry.id).length}
              </span>
            </button>
          ))}
        </aside>
        <main className="recruitment-content">
          <div className="recruitment-search-row">
            <label className="recruitment-search">
              <Search size={17} />
              <input
                aria-label="搜索收藏"
                placeholder="搜索企业、标签、网址或备注"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <select
              className="recruitment-sort"
              aria-label="排序方式"
              value={display.sort}
              onChange={(event) =>
                setDisplay({
                  ...display,
                  sort: event.target.value as BookmarkSort,
                })
              }
            >
              <option value="default">默认顺序</option>
              <option value="asc">字母升序</option>
              <option value="desc">字母降序</option>
            </select>
            <div
              className="recruitment-view-toggle"
              role="group"
              aria-label="显示方式"
            >
              <button
                aria-label="卡片视图"
                aria-pressed={display.view === "cards"}
                onClick={() => setDisplay({ ...display, view: "cards" })}
              >
                <LayoutGrid size={15} />
                卡片
              </button>
              <button
                aria-label="列表视图"
                aria-pressed={display.view === "list"}
                onClick={() => setDisplay({ ...display, view: "list" })}
              >
                <List size={15} />
                列表
              </button>
            </div>
            <button
              className="icon-button"
              title="刷新收藏夹"
              aria-label="刷新收藏夹"
              disabled={busy}
              onClick={() => void perform(refresh)}
            >
              <RefreshCw size={17} />
            </button>
          </div>
          <div className="recruitment-filter-row">
            <nav aria-label="企业分类">
              <button
                className={!selectedCategory ? "selected" : ""}
                onClick={() => setCategory("")}
              >
                全部<span>{scoped.length}</span>
              </button>
              {categories.map((entry) => (
                <button
                  key={entry.id}
                  className={selectedCategory === entry.id ? "selected" : ""}
                  onClick={() => setCategory(entry.id)}
                >
                  {entry.name}
                  <span>
                    {scoped.filter((item) => item.category === entry.id).length}
                  </span>
                </button>
              ))}
            </nav>
            <button
              className="text-button"
              disabled={!data || busy}
              onClick={() => setGroupsOpen("categories")}
            >
              管理分类
            </button>
          </div>
          {error && (
            <div className="recruitment-error" role="alert">
              {error}
              <button disabled={busy} onClick={() => void perform(refresh)}>
                刷新重试
              </button>
            </div>
          )}
          {message && (
            <div className="recruitment-notice" role="status">
              {message}
              <button className="text-button" onClick={() => setMessage("")}>
                关闭
              </button>
            </div>
          )}
          {!snapshot ? (
            <div className="recruitment-empty">
              <RefreshCw size={28} />
              <h2>加载中…</h2>
            </div>
          ) : !filtered.length ? (
            <div className="recruitment-empty">
              <div className="recruitment-empty-icon">
                <BookmarkIcon size={32} />
              </div>
              <h2>{items.length ? "无匹配结果" : "暂无收藏"}</h2>
              <div className="actions">
                <button className="primary" onClick={add}>
                  <Plus size={16} />
                  添加收藏
                </button>
                <button
                  onClick={() =>
                    items.length
                      ? (setQuery(""),
                        setDomain(""),
                        setCategory(""),
                        setFavorites(false))
                      : setImporting(true)
                  }
                >
                  {items.length ? "清空筛选" : "导入清单"}
                </button>
              </div>
            </div>
          ) : (
            <div
              className={
                display.view === "cards"
                  ? "recruitment-grid"
                  : "recruitment-list"
              }
            >
              {filtered.map((item) => (
                <BookmarkCard
                  key={item.id}
                  item={item}
                  group={[
                    data?.domains.find((entry) => entry.id === item.domain_id)
                      ?.name,
                    data?.categories.find((entry) => entry.id === item.category)
                      ?.name,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  busy={busy}
                  onTag={setQuery}
                  onFavorite={() =>
                    void perform(() =>
                      saveItem({ ...item, favorite: !item.favorite }),
                    )
                  }
                  onEdit={() => setEditing(item)}
                  onDelete={() => setDeleting(item)}
                />
              ))}
            </div>
          )}
        </main>
      </div>
      {editing && data && (
        <BookmarkEditor
          initial={editing}
          domains={data.domains}
          categories={data.categories}
          onSave={saveItem}
          onRefresh={refresh}
          onClose={() => setEditing(null)}
        />
      )}
      {groupsOpen && data && (
        <GroupsEditor
          initial={data}
          kind={groupsOpen}
          onSave={save}
          onClose={() => setGroupsOpen(null)}
        />
      )}
      {importing && snapshot && (
        <ImportDialog
          snapshot={snapshot}
          onRefresh={refresh}
          onClose={() => setImporting(false)}
          onImported={(value, summary) => {
            ++readGeneration.current;
            setSnapshot(value);
            setError("");
            setMessage(
              `导入完成：新增 ${summary.added} 条，更新 ${summary.updated} 条，跳过 ${summary.skipped} 条`,
            );
          }}
        />
      )}
      {deleting && snapshot && (
        <Dialog title="删除收藏" busy={busy} onClose={() => setDeleting(null)}>
          <div className="recruitment-fields">
            <p>
              删除“{deleting.name}”及其 {deleting.links.length} 个链接？
            </p>
            {error && (
              <p role="alert" className="recruitment-error">
                {error}
              </p>
            )}
          </div>
          <footer>
            <button disabled={busy} onClick={() => setDeleting(null)}>
              取消
            </button>
            <button
              disabled={busy}
              className="danger"
              onClick={() =>
                void perform(async () => {
                  await save({
                    ...snapshot.data,
                    bookmarks: items.filter((item) => item.id !== deleting.id),
                  });
                  setDeleting(null);
                })
              }
            >
              确认删除
            </button>
          </footer>
        </Dialog>
      )}
    </section>
  );
}
