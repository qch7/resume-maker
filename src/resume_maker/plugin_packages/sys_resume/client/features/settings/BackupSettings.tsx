import { useCallback, useEffect, useRef, useState } from "react";
import { api, download } from "@resume-maker/plugin-sdk/shared/lib/api";
import { capabilities } from "@resume-maker/plugin-sdk/shared/lib/capabilities";
import { storage } from "@resume-maker/plugin-sdk/shared/lib/storage";
import { HOST_RECONNECT_MS } from "@resume-maker/plugin-sdk/shared/lib/timing";
import {
  connectWindow,
  locateWindow,
} from "@resume-maker/plugin-sdk/plugins/window";

interface Backup {
  id: string;
  created_at: string;
  size: number;
  kind: "manual" | "automatic" | "unknown";
  reason: string | null;
  restorable: boolean;
  protected: boolean;
  error: string | null;
}

interface RestorePlan {
  id: string;
  digest: string;
  state: string;
  waiting_windows: string[];
  inflight: number;
  tasks: unknown[];
  scopes: unknown[];
  windows_detail: Record<
    string,
    {
      number?: number;
      title?: string;
      status?: string;
      connected?: boolean;
      last_seen?: number;
    }
  >;
}

interface History {
  items: Backup[];
  can_restore: boolean;
  restore: { id: string; state: string; message?: string } | null;
  pending_restore: RestorePlan | null;
}

interface Props {
  active: boolean;
  run: (work: () => Promise<void>) => void;
  registerBeforeClose: (guard: () => Promise<void>) => () => void;
}

const SOURCE = {
  manual: "手动备份",
  automatic: "自动备份",
  unknown: "来源未知",
};
const REASON: Record<string, string> = {
  manual: "手动创建",
  "plugin-change": "插件变更",
  "data-migration": "资料迁移",
  "before-restore": "恢复前备份",
};

/** 历史备份按服务端发布结果展示，恢复复用窗口草稿保存协议 */
export default function BackupSettings(props: Props) {
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{
    action: "restore" | "delete";
    backup: Backup;
  } | null>(null);
  const [plan, setPlan] = useState<RestorePlan | null>(null);
  const currentPlan = useRef<RestorePlan | null>(null);
  const busyRef = useRef(false);
  const reconnecting = useRef(false);
  const confirmCancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirm) confirmCancel.current?.focus();
  }, [confirm]);

  /** 关闭设置时取消尚未执行的恢复，恢复提交后等待服务重连 */
  const beforeClose = useCallback(async () => {
    if (busyRef.current || reconnecting.current)
      throw new Error("正在处理备份，请等待操作完成。");
    const current = currentPlan.current;
    if (current) {
      await api(`/plugins/plans/${current.id}/abort`, "POST", {
        digest: current.digest,
      });
      await connectWindow();
      currentPlan.current = null;
    }
  }, []);
  useEffect(
    () => props.registerBeforeClose(beforeClose),
    [props.registerBeforeClose, beforeClose],
  );

  /** 加载实际文件列表，损坏备份仍保留删除入口 */
  const refresh = useCallback(async (signal?: AbortSignal) => {
    const latest = await api<History>("/backups", "GET", undefined, signal);
    if (!signal?.aborted) {
      setHistory(latest);
      if (latest.pending_restore && !currentPlan.current) {
        currentPlan.current = latest.pending_restore;
        setPlan(latest.pending_restore);
        setStatus("正在继续已确认的备份恢复，等待各窗口保存草稿…");
      }
    }
  }, []);

  useEffect(() => {
    if (!props.active || plan) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    /** 串行刷新可见列表，自动备份发布后进入历史 */
    async function update() {
      try {
        await refresh(controller.signal);
      } catch (failure) {
        if (!controller.signal.aborted) setError((failure as Error).message);
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(() => void update(), 5000);
      }
    }
    void update();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [props.active, plan?.id, refresh]);

  /** 保存当前页面草稿后执行备份操作，失败保留列表供重试 */
  function run(work: () => Promise<void>) {
    props.run(async () => {
      setBusy(true);
      busyRef.current = true;
      setError("");
      try {
        await work();
      } catch (failure) {
        setError((failure as Error).message);
      } finally {
        setBusy(false);
        busyRef.current = false;
      }
    });
  }

  /** 计划引用同步更新，关闭守卫始终针对当前恢复操作 */
  function updatePlan(value: RestorePlan | null) {
    currentPlan.current = value;
    setPlan(value);
  }

  /** 确认后只处理选中的备份，恢复先通知所有窗口保存草稿 */
  async function confirmed() {
    if (!confirm) return;
    const { action, backup } = confirm;
    if (action === "delete") {
      await api(`/backups/${encodeURIComponent(backup.id)}`, "DELETE");
      setConfirm(null);
      setStatus("备份已删除。");
      await refresh();
      return;
    }
    const candidate = await api<RestorePlan>(
      `/backups/${encodeURIComponent(backup.id)}/restore-plan`,
      "POST",
      { generation: capabilities().generation },
    );
    updatePlan(candidate);
    setConfirm(null);
    try {
      const prepared = await api<RestorePlan>(
        `/plugins/plans/${candidate.id}/prepare`,
        "POST",
        { digest: candidate.digest },
      );
      updatePlan(prepared);
      setStatus("正在保存所有窗口的草稿，并等待当前任务结束…");
      await connectWindow();
    } catch (failure) {
      await api(`/plugins/plans/${candidate.id}/abort`, "POST", {
        digest: candidate.digest,
      });
      updatePlan(null);
      throw failure;
    }
  }

  useEffect(() => {
    if (!plan || plan.state === "planned") return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const originalToken = document.querySelector<HTMLMetaElement>(
      'meta[name="resume-token"]',
    )?.content;
    /** 新实例已通过健康观察后保留浏览器恢复副本并重新加载 */
    async function reconnect() {
      const response = await fetch("/", { cache: "no-store" });
      if (!response.ok || !live) return;
      const page = new DOMParser().parseFromString(
        await response.text(),
        "text/html",
      );
      const token = page.querySelector<HTMLMetaElement>(
        'meta[name="resume-token"]',
      )?.content;
      if (!token || token === originalToken) return;
      const ready = await fetch("/api/capabilities", {
        headers: { "x-resume-token": token },
      });
      if (!ready.ok || !(await ready.json()).ready || !live) return;
      const result = await fetch("/api/backups", {
        headers: { "x-resume-token": token },
      });
      if (!result.ok || !live) return;
      const restored = ((await result.json()) as History).restore;
      if (
        restored?.id !== plan!.id ||
        !["committed", "failed"].includes(restored.state)
      )
        return;
      await storage.prepareReload();
      location.reload();
    }
    /** 全部窗口及任务已确认后自动应用一次，重启期间只检查新实例 */
    async function progress() {
      try {
        if (reconnecting.current) {
          await reconnect();
          return;
        }
        const latest = await api<RestorePlan>(`/plugins/plans/${plan!.id}`);
        if (!live) return;
        currentPlan.current = latest;
        setPlan(latest);
        if (
          latest.state === "preparing" &&
          !latest.waiting_windows.length &&
          !latest.inflight &&
          !latest.tasks.length &&
          !latest.scopes.length
        ) {
          reconnecting.current = true;
          setStatus("正在校验备份、保存恢复前资料并重启服务…");
          try {
            await api(`/plugins/plans/${latest.id}/apply`, "POST", {
              digest: latest.digest,
            });
          } catch (failure) {
            // 业务错误尚未停机，网络中断仍按原请求身份等待新实例
            if (failure instanceof Error && "status" in failure) {
              reconnecting.current = false;
              setError(failure.message);
              const outcome = await api<RestorePlan>(
                `/plugins/plans/${latest.id}`,
              );
              if (outcome.state !== "preparing") {
                currentPlan.current = null;
                setPlan(null);
                await refresh();
              }
            }
          }
        } else if (
          ["failed", "cancelled", "interrupted"].includes(latest.state)
        ) {
          currentPlan.current = null;
          setPlan(null);
          setError("恢复未完成，当前资料已保留。");
          await refresh();
        }
      } catch (failure) {
        if (live && !reconnecting.current) setError((failure as Error).message);
      } finally {
        if (live) timer = setTimeout(() => void progress(), HOST_RECONNECT_MS);
      }
    }
    void progress();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [plan?.id, plan?.state, refresh]);

  /** 取消准备恢复后解除全部窗口冻结，已保存草稿继续保留 */
  async function cancel() {
    if (!plan) return;
    await api(`/plugins/plans/${plan.id}/abort`, "POST", {
      digest: plan.digest,
    });
    updatePlan(null);
    setStatus("已取消恢复。");
    await connectWindow();
    await refresh();
  }

  return (
    <>
      <div className="settings-section">
        <h3>导出备份</h3>
        <p className="subtle">手动创建完整备份，保留在历史列表并下载。</p>
        <button
          className="primary"
          disabled={busy || !!plan}
          onClick={() =>
            run(async () => {
              await download("/backups", "resume-maker-backup.zip", "POST");
              setStatus("手动备份已创建并下载。");
              await refresh();
            })
          }
        >
          创建并下载备份
        </button>
      </div>
      <div className="settings-section">
        <h3>历史备份</h3>
        <p className="subtle">
          插件变更、资料迁移、恢复前自动备份。旧备份显示来源未知。
        </p>
        {!history ? (
          <p>正在读取备份…</p>
        ) : !history.items.length ? (
          <p className="subtle">暂无备份。</p>
        ) : (
          <ul className="backup-history">
            {history.items.map((backup) => (
              <li key={backup.id}>
                <div className="backup-summary">
                  <div>
                    <strong>
                      {new Date(backup.created_at).toLocaleString("zh-CN")}
                    </strong>
                    <span
                      className={`backup-source backup-source-${backup.kind}`}
                    >
                      {SOURCE[backup.kind]}
                    </span>
                  </div>
                  <p className="subtle">
                    {REASON[backup.reason ?? ""] ?? "未记录触发原因"} ·{" "}
                    {(backup.size / 1024 / 1024).toFixed(2)} MB
                    {backup.protected ? " · 正在使用" : ""}
                  </p>
                  <code title={backup.id}>{backup.id}</code>
                  {backup.error && <p className="error">{backup.error}</p>}
                </div>
                <div className="backup-actions">
                  <button
                    disabled={busy || !!plan}
                    onClick={() =>
                      run(async () => {
                        await download(
                          `/backups/${encodeURIComponent(backup.id)}/download`,
                          backup.id,
                        );
                      })
                    }
                  >
                    下载
                  </button>
                  <button
                    disabled={
                      busy ||
                      !!plan ||
                      !backup.restorable ||
                      !history.can_restore
                    }
                    onClick={() => setConfirm({ action: "restore", backup })}
                  >
                    恢复
                  </button>
                  <button
                    className="danger"
                    disabled={busy || !!plan || backup.protected}
                    onClick={() => setConfirm({ action: "delete", backup })}
                  >
                    删除
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {history && !history.can_restore && (
          <p className="subtle">
            请通过 Resume Maker 官方启动器运行，以使用一键恢复。
          </p>
        )}
        {history?.restore?.message && (
          <p className="settings-feedback" role="status">
            {history.restore.message}
          </p>
        )}
      </div>
      {confirm && (
        <div
          className="backup-confirm"
          role="alertdialog"
          aria-label={
            confirm.action === "restore" ? "确认恢复备份" : "确认删除备份"
          }
        >
          <strong>
            {confirm.action === "restore" ? "恢复这份备份？" : "删除这份备份？"}
          </strong>
          <p>
            {new Date(confirm.backup.created_at).toLocaleString("zh-CN")} ·{" "}
            {SOURCE[confirm.backup.kind]}
          </p>
          <code>{confirm.backup.id}</code>
          <p>
            {confirm.action === "restore"
              ? "当前资料将恢复到此备份。系统先保存所有窗口草稿、创建恢复前备份，再重启服务；恢复前目录及备份历史继续保留。"
              : "此备份文件将永久删除，当前资料不受影响。"}
          </p>
          <div className="backup-actions">
            <button
              ref={confirmCancel}
              disabled={busy}
              onClick={() => setConfirm(null)}
            >
              取消
            </button>
            <button
              className={confirm.action === "restore" ? "primary" : "danger"}
              disabled={busy}
              onClick={() => run(confirmed)}
            >
              {confirm.action === "restore" ? "确认恢复" : "确认删除"}
            </button>
          </div>
        </div>
      )}
      {plan && !reconnecting.current && (
        <div className="backup-confirm">
          {plan.waiting_windows?.map((id) => {
            const detail = plan.windows_detail?.[id];
            const offline =
              !detail?.connected ||
              Date.now() / 1000 - (detail.last_seen ?? 0) > 10;
            return (
              <div key={id}>
                <p>
                  等待{detail?.title ?? `窗口 ${detail?.number ?? id}`}
                  保存草稿。
                </p>
                {detail?.status && <p className="subtle">{detail.status}</p>}
                <button
                  disabled={busy}
                  onClick={() =>
                    offline
                      ? run(async () => {
                          await api(
                            `/plugins/plans/${plan.id}/retain-window`,
                            "POST",
                            { id, generation: capabilities().generation },
                          );
                        })
                      : locateWindow(id)
                  }
                >
                  {offline ? "保留该窗口恢复副本并继续" : "定位窗口"}
                </button>
              </div>
            );
          })}
          {!!plan.tasks?.length && (
            <button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await api(`/plugins/plans/${plan.id}/cancel-tasks`, "POST", {
                    digest: plan.digest,
                  });
                })
              }
            >
              取消当前任务并继续
            </button>
          )}
          <button disabled={busy} onClick={() => run(cancel)}>
            取消恢复
          </button>
        </div>
      )}
      {status && (
        <p className="settings-feedback" role="status">
          {status}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
