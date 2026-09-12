import { FolderPlus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, download } from "../../shared/lib/api";
import type {
  Conversation,
  Inspection,
  ProviderSettings,
} from "../../shared/types/index";

interface Props {
  initial: "projects" | "templates" | "settings";
  onClose: () => void;
  onChanged: () => Promise<void>;
  run: (work: () => Promise<void>) => void;
}

/** 管理项目导入、模板区间、归档会话与 Provider 配置。 */
export default function Settings(props: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState(props.initial);
  const [archived, setArchived] = useState<Conversation[]>([]);
  const [root, setRoot] = useState("");
  const [candidates, setCandidates] = useState<
    { name: string; roots: string[]; selected: boolean }[]
  >([]);
  const [manualName, setManualName] = useState(""),
    [manualRoots, setManualRoots] = useState("");
  const [templatePath, setTemplatePath] = useState(""),
    [templateName, setTemplateName] = useState("");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [start, setStart] = useState(""),
    [end, setEnd] = useState("");
  const [provider, setProvider] = useState<ProviderSettings>({
    executable: "codex",
    model: "",
    profile: "",
    timeout_seconds: 1200,
  });
  const [dataDir, setDataDir] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      dialog.current?.showModal();
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        dialog.current?.close();
    },
    [],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      void api<Conversation[]>("/conversations/archived")
        .then(setArchived)
        .catch(
          /* 保留可展示的失败原因，并避免已取消请求更新页面。 */ (e) =>
            setNotice(e.message),
        );
    },
    [],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      void api<{ provider: ProviderSettings; data_dir: string }>("/settings")
        .then(
          /* 在异步操作成功后同步结果及相关状态。 */ (value) => {
            setProvider(value.provider);
            setDataDir(value.data_dir);
          },
        )
        .catch(
          /* 保留可展示的失败原因，并避免已取消请求更新页面。 */ (error) =>
            setNotice(error.message),
        );
    },
    [],
  );
  /** 先刷新待保存草稿再执行用户操作，将异常统一显示为页面提示。 */
  function run(work: () => Promise<void>) {
    props.run(
      /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
        setBusy(true);
        setNotice("");
        try {
          await work();
        } finally {
          setBusy(false);
        }
      },
    );
  }
  return (
    <dialog ref={dialog} className="settings-dialog" onCancel={props.onClose}>
      <div className="dialog-title">
        <h2>工作台设置</h2>
        <button
          className="icon-button"
          aria-label="关闭设置"
          onClick={props.onClose}
        >
          <X size={20} />
        </button>
      </div>
      <nav className="tabs">
        <button
          className={tab === "projects" ? "active" : ""}
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () => setTab("projects")
          }
        >
          项目导入
        </button>
        <button
          className={tab === "templates" ? "active" : ""}
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () => setTab("templates")
          }
        >
          Word 模板
        </button>
        <button
          className={tab === "settings" ? "active" : ""}
          onClick={
            /* 响应当前操作按钮，执行对应业务动作。 */ () => setTab("settings")
          }
        >
          Codex 与数据
        </button>
      </nav>
      {tab === "projects" && (
        <div className="settings-body">
          <p className="subtle">
            扫描项目集合后确认归组。每个项目可以关联多个代码目录。
          </p>
          <label>
            项目集合目录
            <input
              placeholder="D:\...\Projects"
              value={root}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                  setRoot(e.target.value)
              }
            />
          </label>
          <button
            disabled={busy || !root.trim()}
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                run(
                  /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                    const value = await api<
                      { name: string; roots: string[] }[]
                    >("/projects/scan", "POST", { path: root });
                    setCandidates(
                      value.map(
                        /* 逐项转换数据，保留当前业务需要的字段。 */ (p) => ({
                          ...p,
                          selected: true,
                        }),
                      ),
                    );
                  },
                )
            }
          >
            扫描目录
          </button>
          {candidates.length > 0 && (
            <>
              <div className="candidates">
                {candidates.map(
                  /* 按稳定标识生成对应的列表条目。 */ (p, index) => (
                    <label className="candidate" key={index}>
                      <input
                        type="checkbox"
                        checked={p.selected}
                        onChange={
                          /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                            setCandidates(
                              /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                                values,
                              ) =>
                                values.map(
                                  /* 逐项转换数据，保留当前业务需要的字段。 */ (
                                    v,
                                    i,
                                  ) =>
                                    i === index
                                      ? { ...v, selected: e.target.checked }
                                      : v,
                                ),
                            )
                        }
                      />
                      <div>
                        <strong>{p.name}</strong>
                        <span>{p.roots.length} 个来源</span>
                        {p.roots.map(
                          /* 按稳定标识生成对应的列表条目。 */ (path) => (
                            <code key={path}>{path}</code>
                          ),
                        )}
                      </div>
                    </label>
                  ),
                )}
              </div>
              <button
                className="primary"
                disabled={
                  busy ||
                  !candidates.some(
                    /* 检查条目是否满足当前选择或校验条件。 */ (p) =>
                      p.selected,
                  )
                }
                onClick={
                  /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                    run(
                      /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                        for (const p of candidates.filter(
                          /* 保留满足当前范围或有效性条件的条目。 */ (p) =>
                            p.selected,
                        ))
                          await api("/projects", "POST", {
                            name: p.name,
                            roots: p.roots,
                          });
                        await props.onChanged();
                        setNotice("选中的项目已导入，已有项目会保留原记录。");
                        setCandidates([]);
                      },
                    )
                }
              >
                <FolderPlus size={16} />
                导入选中项目
              </button>
            </>
          )}
          <details className="manual-import">
            <summary>手动添加一个项目</summary>
            <label>
              项目名称
              <input
                value={manualName}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    setManualName(e.target.value)
                }
              />
            </label>
            <label>
              来源目录（每行一个）
              <textarea
                rows={3}
                value={manualRoots}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    setManualRoots(e.target.value)
                }
              />
            </label>
            <button
              disabled={busy || !manualName.trim() || !manualRoots.trim()}
              onClick={
                /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                      await api("/projects", "POST", {
                        name: manualName,
                        roots: manualRoots
                          .split("\n")
                          .map(
                            /* 逐项转换数据，保留当前业务需要的字段。 */ (v) =>
                              v.trim(),
                          )
                          .filter(Boolean),
                      });
                      await props.onChanged();
                      setManualName("");
                      setManualRoots("");
                      setNotice("项目已添加。");
                    },
                  )
              }
            >
              添加项目
            </button>
          </details>
        </div>
      )}
      {tab === "templates" && (
        <div className="settings-body">
          <p className="subtle">
            保留模板其他栏目，仅替换选定的项目经历区域。原文件保留，每次导入创建独立模板版本。
          </p>
          <label>
            Word 模板路径
            <input
              placeholder="D:\...\简历.docx"
              value={templatePath}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) => {
                  setTemplatePath(e.target.value);
                  setInspection(null);
                }
              }
            />
          </label>
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
                disabled={
                  busy || !start || !end || Number(start) >= Number(end)
                }
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
                        setNotice("模板已保存，可在右侧简历中选择。");
                      },
                    )
                }
              >
                保存模板版本
              </button>
            </>
          )}
        </div>
      )}
      {tab === "settings" && (
        <div className="settings-body">
          <h3>Codex CLI</h3>
          <p className="subtle">
            复用当前 CLI 配置，包括 CCSwitch 的
            Provider。模型留空时继承当前配置。
          </p>
          <label>
            可执行文件
            <input
              value={provider.executable}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                  setProvider({ ...provider, executable: e.target.value })
              }
            />
          </label>
          <div className="form-grid">
            <label>
              模型覆盖（可留空）
              <input
                value={provider.model}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    setProvider({ ...provider, model: e.target.value })
                }
              />
            </label>
            <label>
              CLI Profile（可留空）
              <input
                value={provider.profile}
                onChange={
                  /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                    setProvider({ ...provider, profile: e.target.value })
                }
              />
            </label>
          </div>
          <label>
            单轮超时（秒）
            <input
              type="number"
              min={30}
              max={7200}
              value={provider.timeout_seconds}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                  setProvider({
                    ...provider,
                    timeout_seconds: Number(e.target.value),
                  })
              }
            />
          </label>
          <div className="actions">
            <button
              disabled={busy}
              onClick={
                /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                      await api("/settings/provider", "PUT", provider);
                      setNotice("Provider 设置已保存。");
                    },
                  )
              }
            >
              保存设置
            </button>
            <button
              disabled={busy}
              onClick={
                /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                      await api("/settings/provider", "PUT", provider);
                      const value = await api<{ reply: string }>(
                        "/providers/codex/check",
                        "POST",
                      );
                      setNotice(value.reply);
                    },
                  )
              }
            >
              {busy ? "连接测试中…" : "测试实际连接"}
            </button>
          </div>
          <h3 className="spaced-heading">数据与备份</h3>
          {archived.length > 0 && (
            <details>
              <summary>已归档会话 · {archived.length}</summary>
              {archived.map(
                /* 按稳定标识生成对应的列表条目。 */ (c) => (
                  <div className="section-heading" key={c.id}>
                    <span>{c.title}</span>
                    <button
                      className="text-button"
                      onClick={
                        /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                          run(
                            /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                              await api(`/conversations/${c.id}`, "PATCH", {
                                archived: false,
                              });
                              setArchived(
                                /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                                  v,
                                ) =>
                                  v.filter(
                                    /* 保留满足当前范围或有效性条件的条目。 */ (
                                      x,
                                    ) => x.id !== c.id,
                                  ),
                              );
                              await props.onChanged();
                            },
                          )
                      }
                    >
                      恢复会话
                    </button>
                  </div>
                ),
              )}
            </details>
          )}
          <code className="path">{dataDir}</code>
          <p className="subtle">
            经历、会话、草稿、模板与导出记录保存在本机数据目录中。
          </p>
          <button
            disabled={busy}
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                run(
                  /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                    await download(
                      "/backups",
                      "resume-maker-backup.zip",
                      "POST",
                    );
                    setNotice("备份已下载。");
                  },
                )
            }
          >
            导出完整备份
          </button>
        </div>
      )}
      {notice && (
        <p className="dialog-notice" role="status">
          {notice}
        </p>
      )}
    </dialog>
  );
}
