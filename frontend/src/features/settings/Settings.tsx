import { FolderPlus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import PathInput from "../../shared/components/PathInput";
import { api, download } from "../../shared/lib/api";
import type { Conversation, ProviderSettings } from "../../shared/types/index";
import CodexModels from "./CodexModels";
import Privacy from "./Privacy";

interface Props {
  initial: "projects" | "settings";
  onClose: () => void;
  onChanged: () => Promise<void>;
  run: (work: () => Promise<void>) => void;
}

/** 管理项目导入、归档会话和 Provider 配置 */
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
  const [provider, setProvider] = useState<ProviderSettings>({
    executable: "codex",
    model: "",
    reasoning_effort: "",
    profile: "",
    timeout_seconds: 1200,
    functions: {},
  });
  const [loaded, setLoaded] = useState(false);
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
      .catch(/* 取消后忽略迟到的错误 */ (e) => setNotice(e.message));
  }, []);
  useEffect(() => {
    void api<{ provider: ProviderSettings; data_dir: string }>("/settings")
      .then((value) => {
        setProvider(value.provider);
        setDataDir(value.data_dir);
        setLoaded(true);
      })
      .catch(/* 取消后忽略迟到的错误 */ (error) => setNotice(error.message));
  }, []);
  /** 等待草稿保存后执行操作并显示异常提示 */
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
          className={tab === "settings" ? "active" : ""}
          onClick={() => setTab("settings")}
        >
          Codex 与数据
        </button>
      </nav>
      {tab === "projects" && (
        <div className="settings-body">
          <p className="subtle">
            扫描项目集合后确认归组。关联多个代码目录的项目会同时建立可独立勾选和对话的子项目。
          </p>
          <PathInput
            label="项目集合目录"
            kind="folder"
            placeholder="D:\...\Projects"
            value={root}
            onChange={setRoot}
            disabled={busy}
          />
          <button
            disabled={busy || !root.trim()}
            onClick={() =>
              run(async () => {
                const value = await api<{ name: string; roots: string[] }[]>(
                  "/projects/scan",
                  "POST",
                  { path: root },
                );
                setCandidates(
                  value.map((p) => ({
                    ...p,
                    selected: true,
                  })),
                );
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
            <PathInput
              label="来源目录（每行一个）"
              kind="folder"
              multiline
              value={manualRoots}
              onChange={setManualRoots}
              disabled={busy}
            />
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
      {tab === "settings" && (
        <div className="settings-body">
          <Privacy />
          <h3>模型连接配置</h3>
          <p className="subtle">
            复用 CLI 文件登录和供应商配置，通过专用只读工具分析脱敏副本，无需
            WSL。
          </p>
          <PathInput
            label="Codex 可执行文件（已验证 0.154.0）"
            kind="executable"
            value={provider.executable}
            disabled={busy || !loaded}
            onChange={
              /* 选择本机 CLI 启动文件，保留其他 Provider 设置 */ (value) =>
                setProvider({ ...provider, executable: value })
            }
          />
          <div className="form-grid">
            <label>
              CLI Profile（可留空）
              <input
                disabled={busy || !loaded}
                value={provider.profile}
                onChange={(e) =>
                  setProvider({ ...provider, profile: e.target.value })
                }
              />
            </label>
            <label>
              单轮超时（秒）
              <input
                type="number"
                min={30}
                max={7200}
                value={provider.timeout_seconds}
                disabled={busy || !loaded}
                onChange={(e) =>
                  setProvider({
                    ...provider,
                    timeout_seconds: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <CodexModels
            value={provider}
            disabled={busy || !loaded}
            onChange={setProvider}
          />
          <div className="actions">
            <button
              disabled={busy || !loaded}
              onClick={() =>
                run(async () => {
                  const saved = await api<ProviderSettings>(
                    "/settings/provider",
                    "PUT",
                    provider,
                  );
                  setProvider(saved);
                  setNotice("Codex 设置已保存，将用于新提交的 AI 任务。");
                })
              }
            >
              保存设置
            </button>
            <button
              disabled={busy || !loaded}
              onClick={() =>
                run(async () => {
                  const saved = await api<ProviderSettings>(
                    "/settings/provider",
                    "PUT",
                    provider,
                  );
                  setProvider(saved);
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
