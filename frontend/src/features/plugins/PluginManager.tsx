import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/lib/api";
import { capabilities } from "../../shared/lib/capabilities";
import { connectWindow } from "../../plugins/window";

interface Plugin {
  id: string;
  title: string;
  version: string;
  required: boolean;
  enabled: boolean;
  state: string;
  provides: string[];
  requires: Record<string, string>;
  builtin: boolean;
  environment_lock?: string | null;
  config?: Record<string, unknown>;
  config_schema?: { properties?: Record<string, unknown> };
  reason?: string;
}
interface Plan {
  id: string;
  digest: string;
  affected: string[];
  added: string[];
  removed: string[];
  mode: string;
  waiting_windows?: string[];
  inflight?: number;
  tasks?: { id: string; owner: string; state: string }[];
  windows_detail?: Record<string, { connected?: boolean; last_seen?: number }>;
}

interface Inspection {
  digest: string;
  manifest: {
    id: string;
    title: string;
    version: string;
    permissions: string[];
  };
  missing_dependencies: string[];
  trust_modes: string[];
}

/** 展示完整配置影响，再由用户应用已审查的计划 */
export default function PluginManager({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [configs, setConfigs] = useState<Record<string, string>>({});
  const [packagePath, setPackagePath] = useState("");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [trusted, setTrusted] = useState(false);
  const [status, setStatus] = useState("");
  const [profiles, setProfiles] = useState<Record<string, string[]>>({});
  /** 刷新安装目录不会自行启用新代码 */
  async function reload() {
    const value = await api<{
      plugins: Plugin[];
      profiles: Record<string, string[]>;
      task_persistence_errors: {
        id: string;
        owner: string;
        error_type: string;
      }[];
    }>("/plugins");
    setProfiles(value.profiles);
    if (value.task_persistence_errors.length)
      setError(
        `任务结束记录写入失败：${value.task_persistence_errors.map((item) => `${item.owner} / ${item.id}（${item.error_type}）`).join("，")}。请检查磁盘空间和数据目录权限。`,
      );
    setPlugins(value.plugins);
    setSelected(
      value.plugins.filter((item) => item.enabled).map((item) => item.id),
    );
    setConfigs(
      Object.fromEntries(
        value.plugins.map((item) => [
          item.id,
          JSON.stringify(item.config ?? {}, null, 2),
        ]),
      ),
    );
  }
  useEffect(() => {
    dialog.current?.showModal();
    void reload().catch((failure: Error) => setError(failure.message));
    return () => dialog.current?.close();
  }, []);
  /** 任何依赖冲突都保留当前选择，供用户继续调整 */
  async function preview() {
    setBusy(true);
    setError("");
    try {
      setPlan(
        await api<Plan>("/plugins/plans", "POST", {
          selected,
          generation: capabilities().generation,
          configs: Object.fromEntries(
            plugins
              .filter((item) => item.config !== undefined)
              .map((item) => [item.id, JSON.parse(configs[item.id] || "{}")]),
          ),
        }),
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 先发出冻结通知，再等待当前及其他窗口确认 */
  async function apply() {
    if (!plan) return;
    setBusy(true);
    setError("");
    const path = `/plugins/plans/${plan.id}`;
    try {
      await api(path + "/prepare", "POST", { digest: plan.digest });
      await connectWindow();
      const progress = await api<Plan>(path);
      setPlan(progress);
      if (
        progress.waiting_windows?.length ||
        progress.inflight ||
        progress.tasks?.length
      ) {
        setError("仍有窗口等待保存，请在各窗口完成草稿保存后再次应用。");
        return;
      }
      const applied = await api<{ state: string }>(path + "/apply", "POST", {
        digest: plan.digest,
      });
      if (applied.state === "restart-required") {
        setStatus(
          "配置已保存，当前服务进入维护状态。请重启本机服务后重新打开工作台。",
        );
        setPlan(null);
        return;
      }
      location.reload();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 安装前展示确切摘要、执行信任及缺少的依赖 */
  async function inspectPackage() {
    setBusy(true);
    setError("");
    setTrusted(false);
    try {
      setInspection(
        await api<Inspection>("/plugins/packages/inspect", "POST", {
          path: packagePath,
        }),
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 只安装刚审查的相同产物，已运行的代码升级等待重启 */
  async function installPackage() {
    if (!inspection || !trusted) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ restart_required: boolean }>(
        "/plugins/packages/install",
        "POST",
        {
          path: packagePath,
          digest: inspection.digest,
          trusted_modes: inspection.trust_modes,
        },
      );
      setStatus(
        result.restart_required
          ? "新版本已安装，请重启服务后加载新代码。"
          : "插件已安装，可在列表中选择启用。",
      );
      setInspection(null);
      await reload();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 停用后移除代码安装记录，业务资料继续保留 */
  async function uninstall(id: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/plugins/packages/${encodeURIComponent(id)}`, "DELETE");
      await reload();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 按包内锁定 wheel 准备候选环境，当前进程保持原有解释器 */
  async function prepareEnvironment(id: string) {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ mode: string; launch: string[] | null }>(
        `/plugins/packages/${encodeURIComponent(id)}/environment`,
        "POST",
      );
      setStatus(
        result.launch
          ? `独立环境已准备。停止服务后使用此参数数组启动：${JSON.stringify(result.launch)}`
          : "独立 worker 环境已准备，重启服务后使用。现有任务继续使用原环境。",
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 明确取消任务或保留离线恢复副本后重新查询排空进度 */
  async function resolveWaiting(
    action: "cancel-tasks" | "retain-window",
    id?: string,
  ) {
    if (!plan) return;
    setBusy(true);
    setError("");
    try {
      await api(
        `/plugins/plans/${plan.id}/${action}`,
        "POST",
        id
          ? { id, generation: capabilities().generation }
          : { digest: plan.digest },
      );
      setPlan(await api<Plan>(`/plugins/plans/${plan.id}`));
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 返回编辑前解除准备状态，其他窗口可以继续工作 */
  async function editSelection() {
    if (!plan) return;
    try {
      await api(`/plugins/plans/${plan.id}/abort`, "POST", {
        digest: plan.digest,
      });
      setPlan(null);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  /** 关闭前撤销尚未提交的计划，解除其他窗口的编辑冻结 */
  async function close() {
    if (plan) {
      try {
        await api(`/plugins/plans/${plan.id}/abort`, "POST", {
          digest: plan.digest,
        });
      } catch (failure) {
        setError((failure as Error).message);
        return;
      }
    }
    onClose();
  }
  return (
    <dialog
      ref={dialog}
      className="settings-dialog plugin-manager"
      onCancel={(event) => {
        event.preventDefault();
        void close();
      }}
    >
      <div className="dialog-title">
        <h2>插件管理</h2>
        <button disabled={busy} onClick={() => void close()}>
          关闭
        </button>
      </div>
      <div className="settings-body">
        {status && <p role="status">{status}</p>}
        <p>
          系统插件组成最小工作台。停用能力保留已有资料；依赖尚未满足的组合无法应用。
        </p>
        {error && (
          <p role="alert" className="error-panel">
            {error}
          </p>
        )}
        <div className="row">
          {Object.entries(profiles).map(([name, ids]) => (
            <button
              key={name}
              disabled={busy || !!plan}
              onClick={() => setSelected(ids)}
            >
              {name === "minimal"
                ? "选择最小组合"
                : name === "standard"
                  ? "选择标准组合"
                  : `选择 ${name}`}
            </button>
          ))}
        </div>
        {plugins.map((item) => (
          <div key={item.id}>
            <label className="plugin-choice">
              <input
                type="checkbox"
                checked={selected.includes(item.id)}
                disabled={item.required || busy || !!plan}
                onChange={(event) => {
                  setSelected((values) =>
                    event.target.checked
                      ? [...values, item.id]
                      : values.filter((id) => id !== item.id),
                  );
                }}
              />
              <span>
                <strong>{item.title}</strong>{" "}
                <small>
                  {item.required ? "系统必需" : item.state} · {item.version}
                </small>
                <br />
                <small>{item.id}</small>
                {item.reason && <small>{item.reason}</small>}
              </span>
            </label>
            {!item.builtin && item.environment_lock && (
              <button
                disabled={busy || !!plan}
                onClick={() => void prepareEnvironment(item.id)}
              >
                准备锁定依赖环境
              </button>
            )}
            {!item.builtin && !item.enabled && (
              <button
                disabled={busy || !!plan}
                onClick={() => void uninstall(item.id)}
              >
                卸载代码并保留资料
              </button>
            )}
            {(Object.keys(item.config ?? {}).length > 0 ||
              Object.keys(item.config_schema?.properties ?? {}).length > 0) && (
              <details>
                <summary>{item.title} 配置</summary>
                <textarea
                  aria-label={`${item.title} 配置`}
                  disabled={busy || !!plan}
                  value={configs[item.id] ?? "{}"}
                  onChange={(event) =>
                    setConfigs((values) => ({
                      ...values,
                      [item.id]: event.target.value,
                    }))
                  }
                />
              </details>
            )}
          </div>
        ))}
        {plan ? (
          <section>
            <h3>变更计划</h3>
            <p>新增：{plan.added.join("、") || "无"}</p>
            <p>停用：{plan.removed.join("、") || "无"}</p>
            <p>受影响：{plan.affected.join("、") || "无"}</p>
            <p>生效方式：{plan.mode}；已有资料保留。</p>
            {!!plan.tasks?.length && (
              <div>
                <p>
                  活动任务：
                  {plan.tasks
                    .map((task) => `${task.owner} / ${task.id}`)
                    .join("、")}
                </p>
                <button
                  disabled={busy}
                  onClick={() => void resolveWaiting("cancel-tasks")}
                >
                  取消这些任务并等待结束
                </button>
              </div>
            )}
            {plan.waiting_windows?.map((id) => (
              <div key={id}>
                <p>等待窗口：{id}</p>
                {(!plan.windows_detail?.[id]?.connected ||
                  Date.now() / 1000 -
                    (plan.windows_detail?.[id]?.last_seen ?? 0) >
                    10) && (
                  <button
                    disabled={busy}
                    onClick={() => void resolveWaiting("retain-window", id)}
                  >
                    保留离线恢复副本并继续
                  </button>
                )}
              </div>
            ))}
            <button disabled={busy} onClick={() => void apply()}>
              保存所有窗口草稿并应用
            </button>
            <button disabled={busy} onClick={() => void editSelection()}>
              返回修改选择
            </button>
          </section>
        ) : (
          <button disabled={busy} onClick={() => void preview()}>
            查看变更计划
          </button>
        )}
        {!plan && (
          <section>
            <h3>安装或升级插件</h3>
            <input
              aria-label="插件包路径"
              placeholder="本机 .rmp 文件完整路径"
              value={packagePath}
              onChange={(event) => {
                setPackagePath(event.target.value);
                setInspection(null);
              }}
            />
            <button
              disabled={busy || !packagePath}
              onClick={() => void inspectPackage()}
            >
              检查插件包
            </button>
            {inspection && (
              <div>
                <p>
                  {inspection.manifest.title} · {inspection.manifest.version}
                </p>
                <p>
                  权限：
                  {inspection.manifest.permissions.join("、") || "无额外声明"}
                </p>
                <p>
                  摘要：<code>{inspection.digest}</code>
                </p>
                {!!inspection.missing_dependencies.length && (
                  <p>
                    尚需准备依赖：{inspection.missing_dependencies.join("、")}
                  </p>
                )}
                <label>
                  <input
                    type="checkbox"
                    checked={trusted}
                    onChange={(event) => setTrusted(event.target.checked)}
                  />
                  我信任此插件以 {inspection.trust_modes.join("、")}{" "}
                  模式运行。宿主及 worker 代码具有本机账户权限。
                </label>
                <button
                  disabled={busy || !trusted}
                  onClick={() => void installPackage()}
                >
                  安装已检查的插件包
                </button>
              </div>
            )}
          </section>
        )}
      </div>
    </dialog>
  );
}
