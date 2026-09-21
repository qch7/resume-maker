import { useCallback, useEffect, useRef, useState } from "react";
import {
  Award,
  Check,
  FilePlus2,
  FolderOpen,
  LoaderCircle,
  Plus,
  Search,
  Upload,
  X,
} from "lucide-react";
import { api, ApiError, request } from "../../shared/lib/api";
import type { ResumeDocument } from "../../shared/types";
import HonorEditor from "./HonorEditor";
import HonorImage from "./HonorImage";
import HonorSortControls from "./HonorSortControls";
import { DEFAULT_HONOR_SORT, sortHonors } from "./sort";
import {
  ACCEPT,
  CATEGORIES,
  hasHonor,
  isRecognizing,
  matchesHonor,
  STATUS,
  type Honor,
} from "./model";

/** 提供跨简历复用的荣誉库、批量上传、识别核对和筛选管理 */
export default function HonorLibrary({
  active,
  document,
  resumeName,
  onAdd,
  onRemove,
  onSaved,
}: {
  active: boolean;
  document: ResumeDocument | null;
  resumeName: string;
  onAdd: (honors: Honor[], section: string) => void;
  onRemove: (id: string) => void;
  onSaved: (honor: Honor) => void;
}) {
  const [items, setItems] = useState<Honor[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState(DEFAULT_HONOR_SORT);
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Honor | null>(null);
  const [busy, setBusy] = useState("");
  const [uploading, setUploading] = useState("");
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [target, setTarget] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const uploadLock = useRef(false);
  const fetchSerial = useRef(0);
  const pollDelay = useRef(10000);
  const [refresh, setRefresh] = useState(0);

  /** 请求序号阻止旧轮询覆盖上传或保存后的列表 */
  const reload = useCallback(
    /* 拉取荣誉库并显示可操作的请求错误 */ async () => {
      const serial = ++fetchSerial.current;
      try {
        const result = await api<Honor[]>("/honors");
        if (serial !== fetchSerial.current) return;
        setItems(result);
        setLoaded(true);
        setLoadError("");
        pollDelay.current = result.some(isRecognizing) ? 2000 : 10000;
      } catch (reason) {
        if (serial === fetchSerial.current)
          setLoadError(
            reason instanceof ApiError && reason.status === 404
              ? "荣誉接口尚未加载，请重启服务后刷新。"
              : (reason as Error).message,
          );
      }
    },
    [],
  );
  useEffect(
    /* 荣誉区可见时串行轮询 */ () => {
      if (!active) return;
      let stopped = false;
      let timer: ReturnType<typeof setTimeout>;
      /** 完成一轮后再安排下一轮，其他窗口的变更也能同步到列表 */
      async function poll() {
        await reload();
        if (!stopped) timer = setTimeout(poll, pollDelay.current);
      }
      void poll();
      return /* 停止隐藏功能区的定时请求 */ () => {
        stopped = true;
        clearTimeout(timer);
        ++fetchSerial.current;
      };
    },
    [active, refresh, reload],
  );

  /** 合并最新条目并使旧查询失效后保留当前筛选和选择 */
  function saved(honor: Honor) {
    ++fetchSerial.current;
    setItems(
      /* 单条保存后原位替换，新增荣誉放在前面 */ (current) => [
        honor,
        ...current.filter(/* 移除旧版本 */ (item) => item.id !== honor.id),
      ],
    );
    onSaved(honor);
    setNotice("已保存，关联简历的信息已同步");
  }
  /** 逐个上传，每个文件独立报告结果，失败文件不阻断其他证书 */
  async function upload(files: File[]) {
    if (uploadLock.current || !files.length) return;
    uploadLock.current = true;
    setUploadErrors([]);
    setNotice("");
    let success = 0;
    for (const [index, file] of files.entries()) {
      setUploading(`正在上传 ${index + 1} / ${files.length}：${file.name}`);
      try {
        if (file.size > 20 * 1024 * 1024)
          throw new Error("超过 20 MB，请压缩后上传。");
        const response = await request(
          `/honors/upload?filename=${encodeURIComponent(file.name)}`,
          {
            method: "POST",
            body: file,
            headers: { "content-type": "application/octet-stream" },
          },
        );
        const item = (await response.json()) as Honor;
        ++fetchSerial.current;
        setItems(
          /* 成功上传后立即显示条目和排队状态 */ (current) => [
            item,
            ...current.filter(
              /* 跳过轮询已读取的条目 */ (existing) => existing.id !== item.id,
            ),
          ],
        );
        success++;
      } catch (reason) {
        setUploadErrors(
          /* 保留每个失败文件的名称和原因 */ (current) => [
            ...current,
            `${file.name}：${(reason as Error).message}`,
          ],
        );
      }
    }
    setUploading("");
    uploadLock.current = false;
    setNotice(`已上传 ${success} / ${files.length} 个文件`);
    setRefresh(/* 上传完成立即重新启动较快的识别轮询 */ (value) => value + 1);
  }
  /** 执行重试、取消或删除，错误留在荣誉库内并允许继续操作 */
  async function action(item: Honor, kind: "recognize" | "cancel" | "delete") {
    if (busy) return;
    setBusy(item.id);
    setError("");
    try {
      if (kind === "delete") {
        await api(`/honors/${item.id}?version=${item.version}`, "DELETE");
        ++fetchSerial.current;
        setItems(
          /* 删除后立即移除卡片 */ (current) =>
            current.filter(
              /* 只删除指定荣誉 */ (value) => value.id !== item.id,
            ),
        );
        setSelected(
          /* 清除相应的批量选择 */ (current) =>
            current.filter(/* 保留其他选择 */ (id) => id !== item.id),
        );
        setDeleting(null);
      } else {
        const updated = await api<Honor>(`/honors/${item.id}/${kind}`, "POST");
        ++fetchSerial.current;
        setItems(
          /* 用服务器状态替换当前条目 */ (current) =>
            current.map(
              /* 其他卡片保留 */ (value) =>
                value.id === item.id ? updated : value,
            ),
        );
      }
    } catch (reason) {
      setError((reason as Error).message);
      if (kind === "delete") setDeleting(null);
    } finally {
      setBusy("");
    }
  }
  /** 将选定荣誉复制到当前简历，失败时保留库和选择状态 */
  function add(values: Honor[]) {
    try {
      onAdd(values, target);
      setNotice(`已加入「${resumeName}」草稿`);
      setSelected([]);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }
  /** 解除当前简历引用后保留库卡片，允许随时重新加入 */
  function remove(id: string) {
    onRemove(id);
    setError("");
    setNotice(`已从「${resumeName}」草稿移除，荣誉资料仍保留在库中`);
  }
  const filtered = sortHonors(
    items.filter(
      /* 综合分类、核对状态和搜索词 */ (item) =>
        (!category || item.fields.category === category) &&
        (!status ||
          (status === "ready"
            ? item.status === "ready"
            : item.status !== "ready")) &&
        matchesHonor(item, query),
    ),
    sort,
  );
  const ready = items.filter(
    /* 统计已核对条目 */ (item) => item.status === "ready",
  ).length;
  const processing = items.filter(isRecognizing).length;
  const chosen = items.filter(
    /* 只将当前仍可用的已核对选择加入简历 */ (item) =>
      selected.includes(item.id) &&
      item.status === "ready" &&
      !hasHonor(document, item.id),
  );
  const editingItem = items.find(
    /* 根据标识读取当前最新版本 */ (item) => item.id === editing,
  );

  return (
    <section
      className="honor-library"
      hidden={!active}
      aria-label="荣誉证书管理"
    >
      <header className="honor-heading">
        <h1>荣誉证书</h1>
        <div className="honor-stats" aria-label="荣誉统计">
          <span>
            全部 <strong>{items.length}</strong>
          </span>
          <span>
            已核对 <strong>{ready}</strong>
          </span>
          <span>
            待处理 <strong>{items.length - ready}</strong>
          </span>
          {processing > 0 && (
            <span className="honor-processing">
              <LoaderCircle size={15} className="spin" />
              识别中 {processing}
            </span>
          )}
        </div>
        <button
          onClick={/* 打开没有附件的手动录入表单 */ () => setEditing("new")}
        >
          <Plus size={15} />
          手动添加
        </button>
      </header>
      <div className="honor-content">
        <aside className="honor-sidebar" aria-label="荣誉分类">
          {["", ...CATEGORIES].map(
            /* 每类显示完整库内的数量，搜索不会改变分类统计 */ (value) => (
              <button
                key={value}
                className={category === value ? "active" : ""}
                aria-pressed={category === value}
                onClick={
                  /* 分类变更不清除搜索或核对筛选 */ () => setCategory(value)
                }
              >
                <span>{value || "全部荣誉"}</span>
                <span>
                  {value
                    ? items.filter(
                        /* 按分类统计 */ (item) =>
                          item.fields.category === value,
                      ).length
                    : items.length}
                </span>
              </button>
            ),
          )}
        </aside>
        <div className="honor-main">
          <div
            className={`honor-upload ${dragging ? "dragging" : ""}`}
            data-guide="honor-recognize"
            tabIndex={-1}
            onDragOver={
              /* 文件进入投放区时显示可投放反馈 */ (event) => {
                event.preventDefault();
                setDragging(true);
              }
            }
            onDragLeave={
              /* 离开投放区时恢复普通状态 */ (event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node))
                  setDragging(false);
              }
            }
            onDrop={
              /* 批量拖入和文件选择使用同一上传流程 */ (event) => {
                event.preventDefault();
                setDragging(false);
                void upload(Array.from(event.dataTransfer.files));
              }
            }
          >
            <Upload size={20} />
            <div>
              <h2>{uploading || "拖入证书，自动识别"}</h2>
              <p>PDF / 图片 · 支持批量 · 单文件 ≤20 MB · PDF ≤12 页</p>
            </div>
            <button
              className="primary"
              title="使用设置中的 AI 服务识别；支持 PDF、JPG、PNG、WebP、BMP、TIFF"
              disabled={!!uploading}
              onClick={
                /* 通过原生文件选择器选择本机附件 */ () =>
                  input.current?.click()
              }
            >
              {uploading ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <FilePlus2 size={17} />
              )}
              {uploading ? "上传中…" : "上传证书"}
            </button>
            <input
              ref={input}
              type="file"
              hidden
              multiple
              accept={ACCEPT}
              aria-label="选择证书文件"
              onChange={
                /* 清空选择器以允许再次选择同名文件 */ (event) => {
                  const files = Array.from(event.target.files ?? []);
                  event.target.value = "";
                  void upload(files);
                }
              }
            />
          </div>
          {uploadErrors.length > 0 && (
            <div className="honor-notice error" role="alert">
              <strong>以下文件未上传成功</strong>
              {uploadErrors.map(
                /* 单独保留失败文件，其他上传结果继续可用 */ (
                  message,
                  index,
                ) => (
                  <p key={index}>{message}</p>
                ),
              )}
              <button
                className="text-button"
                onClick={
                  /* 用户阅读后清除这次批量上传错误 */ () => setUploadErrors([])
                }
              >
                收起
              </button>
            </div>
          )}
          {(error || loadError) && (
            <div className="honor-feedback error" role="alert">
              <span>{error || loadError}</span>
              <button
                onClick={
                  /* 主动刷新以恢复断开的列表读取 */ () => {
                    setError("");
                    setRefresh(refresh + 1);
                  }
                }
              >
                刷新重试
              </button>
            </div>
          )}
          {notice && (
            <div className="honor-feedback" role="status">
              <Check size={16} />
              <span>{notice}</span>
              <button
                className="icon-button"
                aria-label="关闭荣誉提示"
                onClick={/* 清除非错误提示 */ () => setNotice("")}
              >
                <X size={14} />
              </button>
            </div>
          )}
          <div
            className="honor-toolbar"
            data-guide="honor-select"
            tabIndex={-1}
          >
            <label className="honor-search">
              <Search size={16} />
              <input
                aria-label="搜索荣誉"
                placeholder="搜索名称、单位、获奖人或编号"
                value={query}
                onChange={
                  /* 即时筛选当前已加载条目 */ (event) =>
                    setQuery(event.target.value)
                }
              />
            </label>
            <select
              aria-label="核对状态"
              value={status}
              onChange={
                /* 按完成状态筛选 */ (event) => setStatus(event.target.value)
              }
            >
              <option value="">全部状态</option>
              <option value="ready">已核对</option>
              <option value="pending">待处理</option>
            </select>
            <HonorSortControls value={sort} onChange={setSort} />
            <select
              className="honor-target"
              aria-label="加入简历的目标栏目"
              value={target}
              onChange={
                /* 指定当前简历中的目标文本栏目 */ (event) =>
                  setTarget(event.target.value)
              }
            >
              <option value="">荣誉证书（默认）</option>
              {document?.sections
                .filter(
                  /* 荣誉只复制到文本栏目 */ (section) =>
                    section.kind === "text",
                )
                .map(
                  /* 保留用户自定义栏目名称 */ (section) => (
                    <option value={section.id} key={section.id}>
                      {section.title}
                      {section.visible ? "" : "（已隐藏）"}
                    </option>
                  ),
                )}
            </select>
            <button
              disabled={!chosen.length}
              onClick={/* 批量复制勾选的已核对条目 */ () => add(chosen)}
            >
              <Plus size={15} />
              加入简历{chosen.length > 0 ? ` (${chosen.length})` : ""}
            </button>
          </div>
          {!loaded && !loadError ? (
            <div className="honor-empty">
              <LoaderCircle className="spin" />
              正在载入荣誉库…
            </div>
          ) : filtered.length === 0 ? (
            <div className="honor-empty">
              <FolderOpen size={26} />
              <p>{items.length ? "无匹配结果" : "暂无荣誉"}</p>
            </div>
          ) : (
            <div className="honor-grid">
              {filtered.map(
                /* 每个证书卡片呈现原件、核心信息和处理入口 */ (item) => {
                  const recognizing = isRecognizing(item);
                  const included = hasHonor(document, item.id);
                  return (
                    <article className="honor-card" key={item.id}>
                      <div className="honor-card-top">
                        <label className="honor-checkbox">
                          <input
                            type="checkbox"
                            aria-label={`选择 ${item.fields.name || item.attachment?.name}`}
                            disabled={item.status !== "ready" || included}
                            checked={selected.includes(item.id)}
                            onChange={
                              /* 独立维护跨筛选的批量选择 */ (event) =>
                                setSelected(
                                  event.target.checked
                                    ? [...selected, item.id]
                                    : selected.filter(
                                        /* 取消指定条目 */ (id) =>
                                          id !== item.id,
                                      ),
                                )
                            }
                          />
                          <span>{item.fields.category}</span>
                        </label>
                        <span
                          className={`honor-status honor-status-${item.status}`}
                        >
                          {recognizing && (
                            <LoaderCircle size={12} className="spin" />
                          )}
                          {STATUS[item.status]}
                        </span>
                      </div>
                      <button
                        className="honor-cover"
                        aria-label={`查看 ${item.fields.name || item.attachment?.name}`}
                        onClick={
                          /* 打开原件和字段的并排核对窗口 */ () =>
                            setEditing(item.id)
                        }
                      >
                        {item.attachment ? (
                          <HonorImage
                            id={item.id}
                            name={item.attachment.name}
                          />
                        ) : (
                          <div className="honor-no-file">
                            <Award size={42} />
                            <span>手动录入</span>
                          </div>
                        )}
                      </button>
                      <div className="honor-card-body">
                        <h3>
                          {item.fields.name ||
                            item.attachment?.name ||
                            "待填写荣誉"}
                        </h3>
                        <p className="honor-award">
                          {[item.fields.level, item.fields.award]
                            .filter(Boolean)
                            .join(" · ") || "等级信息待补充"}
                        </p>
                        <p className="subtle">
                          {item.fields.issuer || "颁发单位待补充"}
                        </p>
                        <p className="subtle">
                          {item.fields.date || "获得日期待补充"}
                          {item.fields.recipient
                            ? ` · ${item.fields.recipient}`
                            : ""}
                        </p>
                        {item.error && (
                          <p className="honor-card-error" title={item.error}>
                            {item.error}
                          </p>
                        )}
                        {included && (
                          <p className="honor-included">
                            <Check size={13} />
                            已在当前简历
                          </p>
                        )}
                      </div>
                      <div className="honor-card-actions">
                        <button
                          onClick={
                            /* 打开详细资料表单 */ () => setEditing(item.id)
                          }
                        >
                          {item.status === "review" ? "核对信息" : "查看与编辑"}
                        </button>
                        <button
                          disabled={!included && item.status !== "ready"}
                          title={
                            included
                              ? "仅从当前简历移除，保留荣誉资料和原件"
                              : item.status !== "ready"
                                ? "请先核对并保存荣誉信息"
                                : "关联到当前简历，资料随荣誉库同步"
                          }
                          onClick={
                            /* 根据当前简历引用状态切换加入和移除 */ () =>
                              included ? remove(item.id) : add([item])
                          }
                        >
                          {included ? <X size={14} /> : <Plus size={14} />}
                          {included ? "从简历中移除" : "加入简历"}
                        </button>
                      </div>
                      <div className="honor-card-secondary">
                        {item.attachment && (
                          <button
                            className="text-button"
                            disabled={busy === item.id}
                            onClick={
                              /* 识别过程允许取消，完成后允许重新识别 */ () => {
                                void action(
                                  item,
                                  recognizing ? "cancel" : "recognize",
                                );
                              }
                            }
                          >
                            {recognizing ? "取消识别" : "重新识别"}
                          </button>
                        )}
                        <button
                          className="text-button danger-hover"
                          disabled={busy === item.id}
                          onClick={
                            /* 展开具体条目的删除确认以免误删原件 */ () =>
                              setDeleting(item)
                          }
                        >
                          删除
                        </button>
                      </div>
                    </article>
                  );
                },
              )}
            </div>
          )}
        </div>
      </div>
      {editing !== null && (editing === "new" || editingItem) && (
        <HonorEditor
          key={editing}
          honor={editingItem ?? null}
          onClose={/* 关闭后保留列表的筛选和滚动位置 */ () => setEditing(null)}
          onSaved={saved}
        />
      )}
      {deleting && (
        <div className="honor-delete-banner" role="alert">
          <div>
            删除「{deleting.fields.name || deleting.attachment?.name}
            」及其证书原件？<p>已加入简历的文字会保留。</p>
          </div>
          <button
            disabled={!!busy}
            onClick={/* 放弃删除，保留原件和条目 */ () => setDeleting(null)}
          >
            保留
          </button>
          <button
            className="danger"
            disabled={!!busy}
            onClick={
              /* 使用确认时版本删除以免覆盖其他窗口的修改 */ () => {
                void action(deleting, "delete");
              }
            }
          >
            {busy ? "删除中…" : "确认删除"}
          </button>
        </div>
      )}
    </section>
  );
}
