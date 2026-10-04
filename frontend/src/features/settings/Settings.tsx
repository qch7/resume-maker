import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import PathInput from "../../shared/components/PathInput";
import { api, download } from "../../shared/lib/api";
import ActivitySettings from "./ActivitySettings";
import { DEFAULT_ACTIVITY_PREFERENCES } from "../../shared/lib/activityPreferences";
import type { useActivityPreferences } from "../../shared/hooks/useActivityPreferences";
import Privacy from "./Privacy";
import { pluginSettingsPages } from "../../plugins/runtime";
import { hasPlugin } from "../../shared/lib/capabilities";

interface Props {
  initial: "projects" | "settings" | "activity";
  activityPreferences: ReturnType<typeof useActivityPreferences>;
  onActivityDeleted: () => void;
  onClose: () => void;
  onChanged: () => Promise<void>;
  run: (work: () => Promise<void>) => void;
}

/** 分页管理项目导入、模型连接、隐私保护、收藏夹和系统日志 */
export default function Settings(props: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const initial =
    pluginSettingsPages().find((page) => page.openFor?.includes(props.initial))
      ?.id ?? props.initial;
  const [tab, setTab] = useState<string>(initial);
  const [activityVisited, setActivityVisited] = useState(
    props.initial === "activity",
  );
  const [visited, setVisited] = useState<Set<string>>(() => new Set([initial]));
  const {
    preferences,
    setPreferences,
    error: activityError,
  } = props.activityPreferences;
  const [manualName, setManualName] = useState(""),
    [manualRoots, setManualRoots] = useState("");
  const [dataDir, setDataDir] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  useEffect(() => {
    void api<{ data_dir: string }>("/settings")
      .then((value) => {
        setDataDir(value.data_dir);
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
          新建项目
        </button>
        <button
          className={tab === "settings" ? "active" : ""}
          onClick={() => setTab("settings")}
        >
          数据和备份
        </button>
        <button
          className={tab === "privacy" ? "active" : ""}
          onClick={() => setTab("privacy")}
        >
          隐私保护
        </button>
        <button
          className={tab === "activity" ? "active" : ""}
          onClick={() => {
            setTab("activity");
            setActivityVisited(true);
          }}
        >
          系统日志
        </button>
        {pluginSettingsPages().map((page) => (
          <button
            key={page.id}
            className={tab === page.id ? "active" : ""}
            onClick={() => {
              setTab(page.id);
              setVisited((current) => new Set([...current, page.id]));
            }}
          >
            {page.title}
          </button>
        ))}
      </nav>
      {tab === "projects" && (
        <div className="settings-body">
          <details
            className="manual-import"
            open={!hasPlugin("ext.source-code")}
          >
            <summary>手动添加一个项目</summary>
            <label>
              项目名称
              <input
                value={manualName}
                onChange={(e) => setManualName(e.target.value)}
              />
            </label>
            {hasPlugin("ext.source-code") && (
              <PathInput
                label="来源目录（选填，每行一个）"
                kind="folder"
                multiline
                value={manualRoots}
                onChange={setManualRoots}
                disabled={busy}
              />
            )}
            <button
              disabled={busy || !manualName.trim()}
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
          <h3 className="spaced-heading">数据和备份</h3>
          <code className="path">{dataDir}</code>
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
      <div className="settings-body" hidden={tab !== "privacy"}>
        <Privacy />
      </div>
      {pluginSettingsPages()
        .filter((page) => visited.has(page.id))
        .map((page) => (
          <div className="settings-body" key={page.id} hidden={tab !== page.id}>
            <page.component
              active={tab === page.id}
              run={props.run}
              onChanged={props.onChanged}
            />
          </div>
        ))}
      {activityVisited && (
        <div className="settings-body" hidden={tab !== "activity"}>
          <ActivitySettings
            rules={preferences.hiddenRules}
            onDeleted={props.onActivityDeleted}
            onSave={(hiddenRules) =>
              setPreferences((current) => ({ ...current, hiddenRules }))
            }
            onResetLayout={() =>
              setPreferences((current) => ({
                ...current,
                overviewHeight: DEFAULT_ACTIVITY_PREFERENCES.overviewHeight,
                detailWidth: DEFAULT_ACTIVITY_PREFERENCES.detailWidth,
                detailHeight: DEFAULT_ACTIVITY_PREFERENCES.detailHeight,
              }))
            }
          />
          {activityError && <p role="alert">{activityError}</p>}
        </div>
      )}
      {notice && ["projects", "settings"].includes(tab) && (
        <p className="dialog-notice" role="status">
          {notice}
        </p>
      )}
    </dialog>
  );
}
