import {
  DatabaseBackup,
  FolderOpen,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import PathInput from "@resume-maker/plugin-sdk/shared/components/PathInput";
import { api, download } from "@resume-maker/plugin-sdk/shared/lib/api";
import ActivitySettings from "./ActivitySettings";
import { DEFAULT_ACTIVITY_PREFERENCES } from "@resume-maker/plugin-sdk/shared/lib/activityPreferences";
import type { useActivityPreferences } from "@resume-maker/plugin-sdk/shared/hooks/useActivityPreferences";
import Privacy from "./Privacy";
import { pluginSettingsPages } from "@resume-maker/plugin-sdk/plugins/runtime";
import { hasPlugin } from "@resume-maker/plugin-sdk/shared/lib/capabilities";

interface Props {
  initial: string;
  activityPreferences: ReturnType<typeof useActivityPreferences>;
  onActivityDeleted: () => void;
  onClose: () => void;
  onChanged: () => Promise<void>;
  run: (work: () => Promise<void>) => void;
}

/** 固定设置窗口大小，按分类保留表单并在内容区滚动 */
export default function Settings(props: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const content = useRef<HTMLElement>(null);
  const pages = pluginSettingsPages();
  const initialPage = pages.find(
    (page) =>
      page.id === props.initial || page.openFor?.includes(props.initial),
  );
  const initial = initialPage?.group ?? initialPage?.id ?? props.initial;
  const [tab, setTab] = useState(initial);
  const [visited, setVisited] = useState(() => new Set([initial]));
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState("");
  const closingRequest = useRef(false);
  const closeGuards = useRef(new Set<() => Promise<void>>());
  const {
    preferences,
    defaultRules,
    setPreferences,
    error: activityError,
  } = props.activityPreferences;
  const [manualName, setManualName] = useState("");
  const [manualRoots, setManualRoots] = useState("");
  const [dataDir, setDataDir] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const sections = [
    { id: "projects", title: "项目", order: 10, icon: FolderOpen },
    { id: "privacy", title: "隐私", order: 40, icon: ShieldCheck },
    { id: "settings", title: "备份", order: 50, icon: DatabaseBackup },
    { id: "activity", title: "日志", order: 60, icon: ScrollText },
    ...pages
      .filter((page) => !page.group)
      .map((page) => ({
        ...page,
        icon: page.icon ?? SlidersHorizontal,
      })),
  ].sort(
    (left, right) =>
      left.order - right.order || left.id.localeCompare(right.id),
  );
  const currentSection =
    sections.find((section) => section.id === tab) ?? sections[0];

  useEffect(() => {
    setTab(initial);
    setVisited((current) => new Set([...current, initial]));
  }, [initial]);
  useEffect(() => {
    if (content.current) content.current.scrollTop = 0;
  }, [tab]);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void api<{ data_dir: string }>(
      "/settings",
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setDataDir(value.data_dir);
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setNotice(error.message);
      });
    return () => controller.abort();
  }, []);
  /** 设置贡献可在关闭前撤销尚未提交的操作 */
  const registerBeforeClose = useCallback((guard: () => Promise<void>) => {
    closeGuards.current.add(guard);
    return () => {
      closeGuards.current.delete(guard);
    };
  }, []);
  /** 等待各页完成收尾，失败时保留窗口供重试 */
  async function close() {
    if (closingRequest.current || busy) return;
    closingRequest.current = true;
    setClosing(true);
    setCloseError("");
    try {
      for (const guard of closeGuards.current) await guard();
      props.onClose();
    } catch (failure) {
      setCloseError((failure as Error).message);
    } finally {
      closingRequest.current = false;
      setClosing(false);
    }
  }
  /** 切换分类时保留已经访问的表单和草稿 */
  function selectSection(id: string) {
    setTab(id);
    setVisited((current) => new Set([...current, id]));
    setCloseError("");
  }
  /** 等待草稿保存后执行操作并显示结果 */
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
    <dialog
      ref={dialog}
      className="settings-dialog workspace-settings"
      aria-labelledby="workspace-settings-title"
      onCancel={(event) => {
        event.preventDefault();
        void close();
      }}
    >
      <header className="settings-window-header">
        <h2 id="workspace-settings-title">设置</h2>
        <button
          className="icon-button"
          aria-label="关闭设置"
          disabled={closing || busy}
          onClick={() => void close()}
        >
          <X size={20} />
        </button>
      </header>
      <div className="settings-window-layout" inert={closing}>
        <nav className="settings-navigation" aria-label="设置分类">
          {sections.map((section) => (
            <button
              key={section.id}
              className={currentSection.id === section.id ? "active" : ""}
              aria-current={
                currentSection.id === section.id ? "page" : undefined
              }
              onClick={() => selectSection(section.id)}
            >
              <section.icon size={19} />
              <span>{section.title}</span>
            </button>
          ))}
        </nav>
        <main className="settings-content" ref={content}>
          <h2 className="settings-page-title">{currentSection.title}</h2>
          <section hidden={tab !== "projects"} aria-label="项目设置">
            <div className="settings-section">
              <h3>新建项目</h3>
              <p className="subtle">
                只填名称即可创建手工项目，无需源码目录或模型连接。
              </p>
              <label>
                名称
                <input
                  value={manualName}
                  disabled={busy}
                  onChange={(event) => setManualName(event.target.value)}
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
                className="primary"
                disabled={busy || !manualName.trim()}
                onClick={() =>
                  run(async () => {
                    await api("/projects", "POST", {
                      name: manualName,
                      roots: manualRoots
                        .split("\n")
                        .map((value) => value.trim())
                        .filter(Boolean),
                    });
                    await props.onChanged();
                    setManualName("");
                    setManualRoots("");
                    setNotice("项目已创建。");
                  })
                }
              >
                {busy ? "创建中…" : "创建项目"}
              </button>
            </div>
            {pages
              .filter(
                (page) => page.group === "projects" && visited.has("projects"),
              )
              .map((page) => (
                <section className="settings-section" key={page.id}>
                  <h3>{page.title}</h3>
                  <page.component
                    active={tab === "projects"}
                    run={props.run}
                    onChanged={props.onChanged}
                    registerBeforeClose={registerBeforeClose}
                  />
                </section>
              ))}
            {notice && (
              <p className="settings-feedback" role="status">
                {notice}
              </p>
            )}
          </section>
          <section hidden={tab !== "settings"} aria-label="备份设置">
            <h3>资料目录</h3>
            <code className="path">{dataDir || "读取中…"}</code>
            <div className="settings-section">
              <h3>导出备份</h3>
              <p className="subtle">保存简历、模板和设置。</p>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await download(
                      "/backups",
                      "resume-maker-backup.zip",
                      "POST",
                    );
                    setNotice("备份已下载。");
                  })
                }
              >
                下载备份
              </button>
            </div>
            {notice && (
              <p className="settings-feedback" role="status">
                {notice}
              </p>
            )}
          </section>
          {visited.has("privacy") && (
            <section hidden={tab !== "privacy"}>
              <Privacy />
            </section>
          )}
          {pages
            .filter((page) => !page.group && visited.has(page.id))
            .map((page) => (
              <section
                key={page.id}
                hidden={tab !== page.id}
                aria-label={`${page.title}设置`}
              >
                <page.component
                  active={tab === page.id}
                  run={props.run}
                  onChanged={props.onChanged}
                  registerBeforeClose={registerBeforeClose}
                />
              </section>
            ))}
          {visited.has("activity") && (
            <section hidden={tab !== "activity"}>
              <ActivitySettings
                rules={preferences.hiddenRules}
                defaultRules={defaultRules}
                showStarts={preferences.showStarts}
                onDeleted={props.onActivityDeleted}
                onSave={(hiddenRules, showStarts) =>
                  setPreferences((current) => ({
                    ...current,
                    hiddenRules,
                    showStarts,
                  }))
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
            </section>
          )}
        </main>
      </div>
      {closeError && (
        <p className="settings-close-error" role="alert">
          {closeError}
        </p>
      )}
    </dialog>
  );
}
