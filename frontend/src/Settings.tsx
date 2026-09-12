import { useEffect, useRef, useState } from "react";
import { FolderPlus, X } from "lucide-react";
import { api, download } from "./api";
import type { Conversation, Inspection, ProviderSettings } from "./types";

interface Props {
  initial: "projects" | "templates" | "settings";
  onClose: () => void;
  onChanged: () => Promise<void>;
  run: (work: () => Promise<void>) => void;
}

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
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  useEffect(() => {
    void api<Conversation[]>("/conversations/archived")
      .then(setArchived)
      .catch((e) => setNotice(e.message));
  }, []);
  useEffect(() => {
    void api<{ provider: ProviderSettings; data_dir: string }>("/settings")
      .then((value) => {
        setProvider(value.provider);
        setDataDir(value.data_dir);
      })
      .catch((error) => setNotice(error.message));
  }, []);
  function run(work: () => Promise<void>) {
    props.run(async () => {
      setBusy(true);
      setNotice("");
      try {
        await work();
      } finally {
        setBusy(false);
      }
    });
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
          onClick={() => setTab("projects")}
        >
          项目导入
        </button>
        <button
          className={tab === "templates" ? "active" : ""}
          onClick={() => setTab("templates")}
        >
          Word 模板
        </button>
        <button
          className={tab === "settings" ? "active" : ""}
          onClick={() => setTab("settings")}
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
              onChange={(e) => setRoot(e.target.value)}
            />
          </label>
          <button
            disabled={busy || !root.trim()}
            onClick={() =>
              run(async () => {
                const value = await api<{ name: string; roots: string[] }[]>(
                  "/projects/scan",
                  "POST",
                  { path: root },
                );
                setCandidates(value.map((p) => ({ ...p, selected: true })));
              })
            }
          >
            扫描目录
          </button>
          {candidates.length > 0 && (
            <>
              <div className="candidates">
                {candidates.map((p, index) => (
                  <label className="candidate" key={index}>
                    <input
                      type="checkbox"
                      checked={p.selected}
                      onChange={(e) =>
                        setCandidates((values) =>
                          values.map((v, i) =>
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
                      {p.roots.map((path) => (
                        <code key={path}>{path}</code>
                      ))}
                    </div>
                  </label>
                ))}
              </div>
              <button
                className="primary"
                disabled={busy || !candidates.some((p) => p.selected)}
                onClick={() =>
                  run(async () => {
                    for (const p of candidates.filter((p) => p.selected))
                      await api("/projects", "POST", {
                        name: p.name,
                        roots: p.roots,
                      });
                    await props.onChanged();
                    setNotice("选中的项目已导入，已有项目会保留原记录。");
                    setCandidates([]);
                  })
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
                onChange={(e) => setManualName(e.target.value)}
              />
            </label>
            <label>
              来源目录（每行一个）
              <textarea
                rows={3}
                value={manualRoots}
                onChange={(e) => setManualRoots(e.target.value)}
              />
            </label>
            <button
              disabled={busy || !manualName.trim() || !manualRoots.trim()}
              onClick={() =>
                run(async () => {
                  await api("/projects", "POST", {
                    name: manualName,
                    roots: manualRoots
                      .split("\n")
                      .map((v) => v.trim())
                      .filter(Boolean),
                  });
                  await props.onChanged();
                  setManualName("");
                  setManualRoots("");
                  setNotice("项目已添加。");
                })
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
              onChange={(e) => {
                setTemplatePath(e.target.value);
                setInspection(null);
              }}
            />
          </label>
          <button
            disabled={busy || !templatePath.trim()}
            onClick={() =>
              run(async () => {
                const value = await api<Inspection>(
                  "/templates/inspect",
                  "POST",
                  { path: templatePath },
                );
                setInspection(value);
                setStart(value.suggested_start?.toString() ?? "");
                setEnd(value.suggested_end?.toString() ?? "");
                setTemplateName(value.file_name.replace(/\.docx$/i, ""));
              })
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
                  onChange={(e) => setTemplateName(e.target.value)}
                />
              </label>
              <label>
                替换起点（首个项目标题）
                <select
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                >
                  <option value="">选择段落</option>
                  {inspection.paragraphs.map((p) => (
                    <option key={p.index} value={p.index}>
                      {p.index + 1}. {p.text.slice(0, 90) || "空段落"}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                替换终点（下一个需要保留的栏目）
                <select value={end} onChange={(e) => setEnd(e.target.value)}>
                  <option value="">选择段落</option>
                  {inspection.paragraphs.map((p) => (
                    <option key={p.index} value={p.index}>
                      {p.index + 1}. {p.text.slice(0, 90) || "空段落"}
                    </option>
                  ))}
                </select>
              </label>
              {start && end && (
                <div className="template-range">
                  <strong>将替换以下内容</strong>
                  {inspection.paragraphs
                    .filter(
                      (p) =>
                        p.index >= Number(start) &&
                        p.index < Number(end) &&
                        p.text.trim(),
                    )
                    .map((p) => (
                      <p key={p.index}>{p.text}</p>
                    ))}
                </div>
              )}
              <button
                className="primary"
                disabled={
                  busy || !start || !end || Number(start) >= Number(end)
                }
                onClick={() =>
                  run(async () => {
                    await api("/templates", "POST", {
                      path: templatePath,
                      name: templateName,
                      start: Number(start),
                      end: Number(end),
                    });
                    await props.onChanged();
                    setNotice("模板已保存，可在右侧简历中选择。");
                  })
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
              onChange={(e) =>
                setProvider({ ...provider, executable: e.target.value })
              }
            />
          </label>
          <div className="form-grid">
            <label>
              模型覆盖（可留空）
              <input
                value={provider.model}
                onChange={(e) =>
                  setProvider({ ...provider, model: e.target.value })
                }
              />
            </label>
            <label>
              CLI Profile（可留空）
              <input
                value={provider.profile}
                onChange={(e) =>
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
              onChange={(e) =>
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
              onClick={() =>
                run(async () => {
                  await api("/settings/provider", "PUT", provider);
                  setNotice("Provider 设置已保存。");
                })
              }
            >
              保存设置
            </button>
            <button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await api("/settings/provider", "PUT", provider);
                  const value = await api<{ reply: string }>(
                    "/providers/codex/check",
                    "POST",
                  );
                  setNotice(value.reply);
                })
              }
            >
              {busy ? "连接测试中…" : "测试实际连接"}
            </button>
          </div>
          <h3 className="spaced-heading">数据与备份</h3>
          {archived.length > 0 && (
            <details>
              <summary>已归档会话 · {archived.length}</summary>
              {archived.map((c) => (
                <div className="section-heading" key={c.id}>
                  <span>{c.title}</span>
                  <button
                    className="text-button"
                    onClick={() =>
                      run(async () => {
                        await api(`/conversations/${c.id}`, "PATCH", {
                          archived: false,
                        });
                        setArchived((v) => v.filter((x) => x.id !== c.id));
                        await props.onChanged();
                      })
                    }
                  >
                    恢复会话
                  </button>
                </div>
              ))}
            </details>
          )}
          <code className="path">{dataDir}</code>
          <p className="subtle">
            经历、会话、草稿、模板与导出记录保存在本机数据目录中。
          </p>
          <button
            disabled={busy}
            onClick={() =>
              run(async () => {
                await download("/backups", "resume-maker-backup.zip", "POST");
                setNotice("备份已下载。");
              })
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
