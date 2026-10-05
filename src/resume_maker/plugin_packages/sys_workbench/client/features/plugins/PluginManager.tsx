import { useEffect, useRef, useState } from "react";
import { api } from "@resume-maker/plugin-sdk/shared/lib/api";
import { capabilities } from "@resume-maker/plugin-sdk/shared/lib/capabilities";
import {
  connectWindow,
  reloadWindow,
} from "@resume-maker/plugin-sdk/plugins/window";
import PackageDownloads from "./PackageDownloads";
import { recoverActivePlan } from "./planRecovery";

interface Plugin {
  id: string;
  plugin?: string;
  multiple?: boolean;
  scope?: "application" | "workspace" | "task";
  title: string;
  version: string;
  required: boolean;
  enabled: boolean;
  state: string;
  provides: string[];
  requires: Record<
    string,
    string | { provider?: string; cardinality?: string }
  >;
  builtin: boolean;
  dependencies?: Record<string, Record<string, unknown>>;
  provided?: Record<string, Record<string, unknown>>;
  environment_lock?: string | null;
  config?: Record<string, unknown>;
  config_provenance?: Record<string, string>;
  config_schema?: { properties?: Record<string, unknown> };
  reason?: string;
}
interface InstanceSpec {
  id: string;
  plugin: string;
  bindings: Record<string, Record<string, string>>;
}
interface Candidate {
  path: string;
  digest: string;
  trusted_modes: string[];
  id: string;
  title: string;
  version: string;
  enable: boolean;
}
interface Plan {
  data_intents?: { owner: string; from: number; to: number }[];
  state?: string;
  stage?: string;
  message?: string;
  expires_at?: number;
  package_updates?: Record<string, { version: string; digest: string }>;

  id: string;
  digest: string;
  affected: string[];
  added: string[];
  removed: string[];
  mode: string;
  configuration?: {
    configs: Record<string, unknown>;
    provenance: Record<string, unknown>;
    digest: string;
  };
  waiting_windows?: string[];
  inflight?: number;
  tasks?: { id: string; owner: string; state: string }[];
  scopes?: { kind: string; id: string }[];
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
  const [configEdits, setConfigEdits] = useState<
    { instance: string; operation: "reset"; path: string[] }[]
  >([]);
  const [packagePath, setPackagePath] = useState("");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [trusted, setTrusted] = useState(false);
  const [status, setStatus] = useState("");
  const [migrationAccepted, setMigrationAccepted] = useState(false);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [pins, setPins] = useState<
    Record<string, { version: string; digest: string }>
  >({});
  const [packages, setPackages] = useState<
    Record<string, { version: string; digest: string }>
  >({});
  const [profiles, setProfiles] = useState<Record<string, string[]>>({});
  const [instances, setInstances] = useState<InstanceSpec[]>([]);
  const [instancePlugin, setInstancePlugin] = useState("");
  const [instanceName, setInstanceName] = useState("");
  /** 刷新安装目录不会自行启用新代码 */
  async function reload() {
    const value = await api<{
      plugins: Plugin[];
      pins: Record<string, { version: string; digest: string }>;
      packages: Record<string, { version: string; digest: string }>;
      profiles: Record<string, string[]>;
      instances: InstanceSpec[];
      task_persistence_errors: {
        id: string;
        owner: string;
        error_type: string;
      }[];
    }>("/plugins");
    setProfiles(value.profiles);
    setPins(value.pins ?? {});
    setPackages(value.packages ?? {});
    const operations = await api<Plan[]>("/plugins/operations");
    const latest = recoverActivePlan(operations);
    if (latest) setPlan(latest);
    const recent = [...operations].sort(
      (a, b) => (b.expires_at ?? 0) - (a.expires_at ?? 0),
    )[0];
    if (!latest && recent?.message) setStatus(recent.message);
    setConfigEdits([]);
    setInstances(value.instances ?? []);
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
          instances,
          generation: capabilities().generation,
          configs: Object.fromEntries(
            plugins
              .filter(
                (item) =>
                  item.config !== undefined &&
                  (item.state === "待应用" ||
                    configs[item.id] !== JSON.stringify(item.config, null, 2)),
              )
              .map((item) => [item.id, JSON.parse(configs[item.id] || "{}")]),
          ),
          config_edits: configEdits,
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
    if (plan.data_intents?.length && !migrationAccepted) {
      setBusy(false);
      setError("请先确认资料迁移及恢复方式。");
      return;
    }
    const path = `/plugins/plans/${plan.id}`;
    try {
      await api(path + "/prepare", "POST", { digest: plan.digest });
      await connectWindow();
      const progress = await api<Plan>(path);
      setPlan(progress);
      if (
        progress.waiting_windows?.length ||
        progress.inflight ||
        progress.tasks?.length ||
        progress.scopes?.length
      ) {
        setError("仍有窗口等待保存，请在各窗口完成草稿保存后再次应用。");
        return;
      }
      const applied = await api<{ state: string }>(path + "/apply", "POST", {
        digest: plan.digest,
      });
      if (applied.state === "validating") {
        setPlan(await api<Plan>(path));
        return;
      }
      if (applied.state === "restart-required") {
        setStatus(
          "配置已保存，当前服务进入维护状态。请重启本机服务后重新打开工作台。",
        );
        setPlan(null);
        return;
      }
      await reloadWindow();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (
      !plan ||
      !["validating", "restart-required", "booting", "applying"].includes(
        plan.state ?? "",
      )
    )
      return;
    let live = true;
    let running = false;
    /** 候选结果按持久操作身份查询，服务换代后重新加载工作台 */
    async function poll() {
      if (running) return;
      running = true;
      try {
        const latest = await api<Plan>(`/plugins/plans/${plan!.id}`);
        if (!live) return;
        setPlan(latest);
        if (["committed", "rolled-back"].includes(latest.state ?? ""))
          await reloadWindow();
        if (
          ["failed", "cancelled", "interrupted", "recovery-required"].includes(
            latest.state ?? "",
          )
        ) {
          setStatus(latest.message ?? "候选验证已结束，原有组合继续保留。");
          setPlan(null);
        }
      } catch {
        if (live) {
          setStatus("服务正在重新启动，正在恢复连接。");
          try {
            const response = await fetch("/", { cache: "no-store" });
            if (response.ok && live) await reloadWindow();
          } catch {
            /* 监督器尚未重新开放监听 */
          }
        }
      } finally {
        running = false;
      }
    }
    const timer = setInterval(() => void poll(), 1000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [plan?.id, plan?.state]);
  /** 取消候选验证仍须等待独立宿主和安装进程真实退出 */
  async function cancelValidation() {
    if (!plan) return;
    try {
      setPlan(
        await api<Plan>(`/plugins/plans/${plan.id}/cancel-validation`, "POST"),
      );
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  /** 把审查过的多个包作为一个依赖集合提交，用户继续确认影响范围 */
  async function previewPackages() {
    setMigrationAccepted(false);
    setBusy(true);
    setError("");
    try {
      const enabled = new Set(selected);
      for (const item of candidates) {
        if (item.enable) enabled.add(item.id);
        else enabled.delete(item.id);
      }
      setPlan(
        await api<Plan>("/plugins/packages/plans", "POST", {
          generation: capabilities().generation,
          packages: candidates.map(({ path, digest, trusted_modes }) => ({
            path,
            digest,
            trusted_modes,
          })),
          selected: [...enabled],
        }),
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 版本锁固定当前包摘要，解除后也不会自动更新 */
  async function togglePin(id: string) {
    setBusy(true);
    setError("");
    try {
      setPins(
        await api(`/plugins/packages/${encodeURIComponent(id)}/pin`, "PUT", {
          digest: pins[id] ? null : packages[id].digest,
        }),
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 添加候选实例时复制配置，应用计划通过前不影响正在运行的插件 */
  function addInstance() {
    const source = plugins.find((item) => item.id === instancePlugin);
    const id = instanceName.trim();
    if (
      !source?.multiple ||
      !/^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/.test(id) ||
      plugins.some((item) => item.id === id)
    ) {
      setError("请选择支持多实例的插件，填写未占用的英文实例名称。");
      return;
    }
    setPlugins((items) => [
      ...items,
      {
        ...source,
        id,
        plugin: source.plugin ?? source.id,
        enabled: false,
        required: false,
        state: "待应用",
      },
    ]);
    setInstances((items) => [
      ...items,
      { id, plugin: source.plugin ?? source.id, bindings: {} },
    ]);
    setConfigs((items) => ({ ...items, [id]: configs[source.id] ?? "{}" }));
    setSelected((items) => [...items, id]);
    setInstanceName("");
  }
  /** 实例移除进入同一变更计划，历史资料仍由其原身份保留 */
  function removeInstance(id: string) {
    setSelected((items) => items.filter((item) => item !== id));
    setPlugins((items) => items.filter((item) => item.id !== id));
    setInstances((items) => items.filter((item) => item.id !== id));
    setConfigEdits((items) => items.filter((item) => item.instance !== id));
  }
  /** 每个消费实例分别选择提供方，清空选择恢复清单约束 */
  function bindProvider(
    item: Plugin,
    domain: string,
    name: string,
    owner: string,
  ) {
    const existing = instances.find((value) => value.id === item.id) ?? {
      id: item.id,
      plugin: item.plugin ?? item.id,
      bindings: {},
    };
    const bindings = { ...existing.bindings[domain] };
    if (owner) bindings[name] = owner;
    else delete bindings[name];
    setInstances((values) => [
      ...values.filter((value) => value.id !== item.id),
      { ...existing, bindings: { ...existing.bindings, [domain]: bindings } },
    ]);
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
    setCandidates((values) => [
      ...values.filter((item) => item.id !== inspection.manifest.id),
      {
        path: packagePath,
        digest: inspection.digest,
        trusted_modes: inspection.trust_modes,
        ...inspection.manifest,
        enable:
          selected.includes(inspection.manifest.id) ||
          !packages[inspection.manifest.id],
      },
    ]);
    setInspection(null);
    setTrusted(false);
    setPackagePath("");
    setStatus("已加入候选清单。可以继续添加其他包，再一起检查和应用。");
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
    if (
      plan &&
      ["validating", "restart-required", "booting", "applying"].includes(
        plan.state ?? "",
      )
    ) {
      onClose();
      return;
    }
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
        {Object.entries(pins)
          .filter(([id]) => !packages[id])
          .map(([id, pin]) => (
            <div className="row" key={id}>
              <span>
                {id} 已卸载，仍保留 {pin.version} 的版本锁
              </span>
              <button
                disabled={busy || !!plan}
                onClick={() => void togglePin(id)}
              >
                解除 {id} 的版本锁
              </button>
            </div>
          ))}
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
        <details>
          <summary>添加独立实例</summary>
          <p>同一插件可使用不同配置和提供方，资料按实例名称分别保留。</p>
          <select
            aria-label="实例使用的插件"
            value={instancePlugin}
            disabled={busy || !!plan}
            onChange={(event) => setInstancePlugin(event.target.value)}
          >
            <option value="">选择插件</option>
            {plugins
              .filter(
                (item) =>
                  item.multiple &&
                  item.id === item.plugin &&
                  item.scope !== "task",
              )
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
          </select>
          <input
            aria-label="新实例名称"
            placeholder="例如 community.my-instance"
            value={instanceName}
            disabled={busy || !!plan}
            onChange={(event) => setInstanceName(event.target.value)}
          />
          <button disabled={busy || !!plan} onClick={addInstance}>
            添加到候选组合
          </button>
        </details>
        {plugins.map((item) => (
          <div key={item.id}>
            <label className="plugin-choice">
              <input
                type="checkbox"
                checked={selected.includes(item.id)}
                disabled={
                  item.required || item.scope === "task" || busy || !!plan
                }
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
            {!item.builtin && packages[item.plugin ?? item.id] && (
              <button
                disabled={busy || !!plan}
                onClick={() => void togglePin(item.plugin ?? item.id)}
              >
                {pins[item.plugin ?? item.id]
                  ? `解除 ${pins[item.plugin ?? item.id].version} 的版本锁`
                  : `锁定当前版本 ${item.version}`}
              </button>
            )}
            {item.plugin && item.plugin !== item.id && (
              <button
                disabled={busy || !!plan}
                onClick={() => removeInstance(item.id)}
              >
                移除实例并保留资料
              </button>
            )}
            {item.scope === "task" && (
              <p>由任务创建独立实例，任务结束后释放。</p>
            )}
            {selected.includes(item.id) &&
              Object.keys(item.dependencies ?? { host: item.requires }).length >
                0 && (
                <details>
                  <summary>{item.id} 使用的提供方</summary>
                  {Object.entries(
                    item.dependencies ?? { host: item.requires },
                  ).flatMap(([domain, dependencies]) =>
                    Object.keys(dependencies).map((name) => (
                      <label key={`${domain}/${name}`}>
                        {domain} / {name}
                        <select
                          aria-label={`${item.id} 的 ${domain}/${name} 提供方`}
                          disabled={busy || !!plan}
                          value={
                            instances.find((value) => value.id === item.id)
                              ?.bindings[domain]?.[name] ?? ""
                          }
                          onChange={(event) =>
                            bindProvider(item, domain, name, event.target.value)
                          }
                        >
                          <option value="">按清单选择</option>
                          {plugins
                            .filter(
                              (candidate) =>
                                selected.includes(candidate.id) &&
                                name in
                                  (candidate.provided?.[
                                    domain === "remote" ? "host" : domain
                                  ] ?? {}),
                            )
                            .map((candidate) => (
                              <option key={candidate.id} value={candidate.id}>
                                {candidate.title} · {candidate.id}
                              </option>
                            ))}
                        </select>
                      </label>
                    )),
                  )}
                </details>
              )}
            {!item.builtin &&
              item.id === item.plugin &&
              item.environment_lock && (
                <button
                  disabled={busy || !!plan}
                  onClick={() => void prepareEnvironment(item.id)}
                >
                  准备锁定依赖环境
                </button>
              )}
            {!item.builtin && item.id === item.plugin && !item.enabled && (
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
                  onChange={(event) => {
                    setConfigEdits((values) =>
                      values.filter((edit) => edit.instance !== item.id),
                    );
                    setConfigs((values) => ({
                      ...values,
                      [item.id]: event.target.value,
                    }));
                  }}
                />
                <p className="subtle">
                  编辑 JSON 会整体替换该实例的工作区配置。null
                  是空值，恢复继承请使用下方操作。
                </p>
                <button
                  disabled={busy || !!plan}
                  onClick={() => {
                    setConfigs((values) => ({
                      ...values,
                      [item.id]: JSON.stringify(item.config ?? {}, null, 2),
                    }));
                    setConfigEdits((values) => [
                      ...values.filter((edit) => edit.instance !== item.id),
                      { instance: item.id, operation: "reset", path: [] },
                    ]);
                  }}
                >
                  恢复全部继承值
                </button>
                {Object.entries(item.config_provenance ?? {}).map(
                  ([path, source]) => (
                    <div key={path} className="row">
                      <span>
                        {path} · 来源：{source}
                      </span>
                      {path !== "/" && (
                        <button
                          disabled={busy || !!plan}
                          onClick={() => {
                            const fields = path
                              .slice(1)
                              .split("/")
                              .map((key) =>
                                key.replaceAll("~1", "/").replaceAll("~0", "~"),
                              );
                            setConfigEdits((values) => [
                              ...values,
                              {
                                instance: item.id,
                                operation: "reset",
                                path: fields,
                              },
                            ]);
                          }}
                        >
                          恢复此字段继承值
                        </button>
                      )}
                    </div>
                  ),
                )}
                {configEdits.some((edit) => edit.instance === item.id) && (
                  <p role="status">已加入恢复操作，查看变更计划后生效。</p>
                )}
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
            <p>
              生效方式：
              {plan.mode === "host-restart"
                ? "验证后重新启动服务"
                : "等待当前操作完成后切换"}
              ；已有资料保留。
            </p>
            {plan.package_updates && (
              <ul>
                {Object.entries(plan.package_updates).map(([id, item]) => (
                  <li key={id}>
                    {id} → {item.version} · 摘要 {item.digest}
                  </li>
                ))}
              </ul>
            )}
            {plan.message && <p role="status">{plan.message}</p>}
            {!!plan.data_intents?.length && (
              <div>
                <p>本次还需升级插件资料：</p>
                <ul>
                  {plan.data_intents.map((item) => (
                    <li key={item.owner}>
                      {item.owner}：版本 {item.from} → {item.to}
                    </li>
                  ))}
                </ul>
                <p>
                  会先在副本完成整组迁移和健康检查，再停机备份并迁移正式资料。正式资料升级后，不自动退回旧代码；失败时保留完整备份并进入恢复状态。
                </p>
                <label>
                  <input
                    type="checkbox"
                    checked={migrationAccepted}
                    onChange={(event) =>
                      setMigrationAccepted(event.target.checked)
                    }
                  />
                  我确认迁移这些资料，了解失败后可能需要恢复完整备份。
                </label>
              </div>
            )}
            {plan.configuration && (
              <details>
                <summary>应用后的配置及字段来源</summary>
                <pre>
                  {JSON.stringify(
                    {
                      configs: plan.configuration.configs,
                      sources: plan.configuration.provenance,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            )}
            {!!plan.scopes?.length && (
              <p>
                等待作用域结束：
                {plan.scopes
                  .map((item) => `${item.kind} / ${item.id}`)
                  .join("、")}
              </p>
            )}
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
            {plan.state === "validating" && (
              <button
                disabled={plan.stage === "cancelling"}
                onClick={() => void cancelValidation()}
              >
                取消验证并等待结束
              </button>
            )}
            <button
              disabled={
                busy ||
                !["planned", "preparing"].includes(plan.state ?? "planned")
              }
              onClick={() => void apply()}
            >
              保存所有窗口草稿并应用
            </button>
            <button
              disabled={
                busy ||
                !["planned", "preparing"].includes(plan.state ?? "planned")
              }
              onClick={() => void editSelection()}
            >
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
            <PackageDownloads
              onChoose={(path) => {
                setPackagePath(path);
                setInspection(null);
              }}
            />
            {!!candidates.length && (
              <div>
                <h4>联合候选清单</h4>
                {candidates.map((item) => (
                  <div key={item.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={item.enable}
                        onChange={(event) =>
                          setCandidates((values) =>
                            values.map((value) =>
                              value.id === item.id
                                ? { ...value, enable: event.target.checked }
                                : value,
                            ),
                          )
                        }
                      />
                      随此次变更启用 {item.title} · {item.version}
                    </label>
                    <button
                      onClick={() =>
                        setCandidates((values) =>
                          values.filter((value) => value.id !== item.id),
                        )
                      }
                    >
                      移出候选
                    </button>
                  </div>
                ))}
                <button disabled={busy} onClick={() => void previewPackages()}>
                  一起检查依赖和变更范围
                </button>
              </div>
            )}
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
                  加入联合候选
                </button>
              </div>
            )}
          </section>
        )}
      </div>
    </dialog>
  );
}
