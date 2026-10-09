export interface StoredValue {
  value: string | null;
  version: number;
}
export interface StorageSnapshot {
  namespace: string;
  values: Record<string, StoredValue>;
}
interface LocalStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  keys(): string[];
}
interface Options {
  read: () => Promise<StorageSnapshot>;
  write: (key: string, value: StoredValue) => Promise<StoredValue>;
  local: LocalStore;
  client: string;
  changed: () => void;
}
interface Entry extends StoredValue {
  pending: boolean;
  error: string;
  conflict: boolean;
}
export interface RecoveryCopy {
  id: string;
  key: string;
  value: string | null;
}

/** 串行保存独立草稿，浏览器日志保护断网输入，版本冲突等待用户处理 */
export function createPersistence(options: Options) {
  const entries = new Map<string, Entry>();
  const recoveries = new Map<string, RecoveryCopy>();
  const adopted = new Map<string, Map<string, string>>();
  let namespace = "";
  let localError = "";
  let recoveryNumber = 0;
  let reloadPrepared = false;
  let chain = Promise.resolve();
  let timer: ReturnType<typeof setTimeout> | undefined;
  /** 每个窗口使用独立日志，避免断网时互相覆盖恢复副本 */
  function journalKey(key: string) {
    return `rm.pending.${namespace}.${options.client}.${encodeURIComponent(key)}`;
  }
  /** 本地存储不可用时继续向数据库保存，并明确提示尚未完成的写入 */
  function journal(key: string, entry: Entry) {
    try {
      options.local.setItem(journalKey(key), JSON.stringify({ key, ...entry }));
      localError = "";
    } catch {
      localError = "浏览器恢复副本不可用，请等待本机保存完成后再关闭页面。";
    }
  }
  /** 删除已确认的本窗口副本，不删除其他窗口的新输入 */
  function clearJournal(key: string) {
    try {
      options.local.removeItem(journalKey(key));
    } catch {
      // 数据库已经确认，残留副本在下次启动按值核对
    }
  }
  /** 只处理接管时的原副本，新写入的其他窗口内容仍保留为待同步输入 */
  function settleAdopted(key: string, confirmed: string | null) {
    for (const [id, original] of adopted.get(key) ?? []) {
      try {
        if (options.local.getItem(id) !== original) continue;
        const copy = JSON.parse(original) as StoredValue & { key: string };
        if (copy.value === confirmed) options.local.removeItem(id);
        else {
          options.local.setItem(
            id,
            JSON.stringify({ ...copy, recovery: true }),
          );
          recoveries.set(id, { id, key, value: copy.value });
          setItem(
            `rm.recovery.${options.client}.${++recoveryNumber}`,
            JSON.stringify({ key, value: copy.value }),
          );
        }
      } catch {
        // 无法更新的副本继续保留，下次启动仍执行版本检查
      }
    }
    adopted.delete(key);
  }
  /** 在渲染表单前恢复数据库及浏览器尚未确认的输入 */
  async function initialize() {
    const snapshot = await options.read();
    entries.clear();
    recoveries.clear();
    adopted.clear();
    namespace = snapshot.namespace;
    for (const [key, value] of Object.entries(snapshot.values))
      entries.set(key, {
        ...value,
        pending: false,
        error: "",
        conflict: false,
      });
    let keys: string[] = [];
    try {
      keys = options.local.keys();
    } catch {
      localError = "浏览器恢复副本不可用，请等待本机保存完成后再关闭页面。";
    }
    for (const id of keys.filter((key) =>
      key.startsWith(`rm.pending.${namespace}.`),
    )) {
      try {
        const original = options.local.getItem(id) ?? "null";
        const saved = JSON.parse(original) as
          | (StoredValue & { key: string; recovery?: boolean })
          | null;
        if (
          !saved ||
          typeof saved.key !== "string" ||
          typeof saved.version !== "number"
        )
          continue;
        const remote = snapshot.values[saved.key] ?? {
          value: null,
          version: 0,
        };
        if (saved.recovery || id.includes(".recovery-")) {
          recoveries.set(id, { id, key: saved.key, value: saved.value });
          continue;
        }
        if (remote.value === saved.value) {
          options.local.removeItem(id);
          continue;
        }
        const current = entries.get(saved.key);
        if (current?.pending && current.value !== saved.value) {
          recoveries.set(id, { id, key: saved.key, value: saved.value });
          setItem(
            `rm.recovery.${options.client}.${++recoveryNumber}`,
            JSON.stringify({ key: saved.key, value: saved.value }),
          );
          options.local.setItem(
            id,
            JSON.stringify({ ...saved, recovery: true }),
          );
          continue;
        }
        const conflict = saved.version !== remote.version;
        entries.set(saved.key, {
          value: saved.value,
          version: saved.version,
          pending: true,
          error: conflict ? "此草稿在其他窗口已有修改，本页输入已保留。" : "",
          conflict,
        });
        journal(saved.key, entries.get(saved.key)!);
        if (id !== journalKey(saved.key)) {
          const copies = adopted.get(saved.key) ?? new Map<string, string>();
          copies.set(id, original);
          adopted.set(saved.key, copies);
        }
      } catch {
        // 损坏的恢复记录保留原位，其他草稿仍可加载
      }
    }
    options.changed();
    schedule();
  }
  /** 连续输入合并后提交，导航和备份可以直接等待 flush */
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => void flush().catch(() => undefined), 300);
  }
  /** 立即保存本地副本，删除保留版本以防过期窗口恢复旧值 */
  function setItem(key: string, value: string | null) {
    const current = entries.get(key);
    if ((current?.value ?? null) === value) return;
    reloadPrepared = false;
    const entry: Entry = {
      value,
      version: current?.version ?? 0,
      pending: true,
      error: current?.error ?? "",
      conflict: current?.conflict ?? false,
    };
    entries.set(key, entry);
    journal(key, entry);
    options.changed();
    schedule();
  }
  /** 写入期间的新输入保留，失败不推进版本，重试同值请求不会重复提交 */
  function flush() {
    clearTimeout(timer);
    const next = chain
      .catch(() => undefined)
      .then(async () => {
        for (const [key, entry] of entries) {
          if (!entry.pending || entry.conflict) continue;
          const submitted = { value: entry.value, version: entry.version };
          try {
            const saved = await options.write(key, submitted);
            const current = entries.get(key)!;
            current.version = saved.version;
            current.error = "";
            current.pending = current.value !== submitted.value;
            if (current.pending) journal(key, current);
            else clearJournal(key);
            settleAdopted(key, submitted.value);
          } catch (error) {
            const current = entries.get(key)!;
            current.error =
              error instanceof Error ? error.message : "本机保存失败";
            current.conflict = (error as { status?: number }).status === 409;
          }
        }
        options.changed();
        if ([...entries.values()].some((entry) => entry.pending))
          throw new Error("仍有草稿未写入本机数据库，请处理保存提示后重试。");
      });
    chain = next;
    return next;
  }
  /** 冲突处理始终重新读取当前版本，保留原值副本供用户核对 */
  async function resolve(key: string, choice: "local" | "remote") {
    await chain.catch(() => undefined);
    const snapshot = await options.read();
    const remote = snapshot.values[key] ?? { value: null, version: 0 };
    const current = entries.get(key)!;
    const id = `rm.pending.${namespace}.recovery-${options.client}.${encodeURIComponent(key)}`;
    const discarded = choice === "local" ? remote.value : current.value;
    if (
      discarded !== null &&
      discarded !== (choice === "local" ? current.value : remote.value)
    ) {
      try {
        options.local.setItem(
          id,
          JSON.stringify({ key, value: discarded, version: remote.version }),
        );
      } catch {
        localError = "浏览器恢复副本不可用，请等待本机保存完成后再关闭页面。";
      }
      recoveries.set(id, { id, key, value: discarded });
      setItem(
        `rm.recovery.${options.client}.${++recoveryNumber}`,
        JSON.stringify({ key, value: discarded }),
      );
    }
    current.version = remote.version;
    current.conflict = false;
    current.error = "";
    if (choice === "remote") current.value = remote.value;
    current.pending = choice === "local" && current.value !== remote.value;
    if (current.pending) journal(key, current);
    else clearJournal(key);
    settleAdopted(key, current.value);
    options.changed();
    if (choice === "local") await flush();
  }
  /** 冲突载入需要重挂表单，其他未同步输入先确认写入数据库或浏览器日志 */
  async function prepareReload() {
    try {
      await flush();
    } catch {
      for (const [key, entry] of entries) {
        if (!entry.pending) continue;
        try {
          options.local.setItem(
            journalKey(key),
            JSON.stringify({ key, ...entry }),
          );
        } catch {
          throw new Error(
            "其他草稿尚未保存且浏览器恢复副本不可用，请重试保存后再载入。",
          );
        }
      }
    }
    reloadPrepared = true;
  }
  return {
    initialize,
    namespace: () => namespace,
    has: (key: string) => entries.has(key),
    getItem: (key: string) => entries.get(key)?.value ?? null,
    setItem,
    removeItem: (key: string) => setItem(key, null),
    keys: () =>
      [...entries.keys()].filter((key) => entries.get(key)?.value !== null),
    flush,
    resolve,
    prepareReload,
    warnBeforeUnload: () =>
      !reloadPrepared && [...entries.values()].some((entry) => entry.pending),
    recoveries: () => {
      const copies = [...recoveries.values()];
      for (const [id, entry] of entries) {
        if (!id.startsWith("rm.recovery.") || entry.value === null) continue;
        try {
          const copy = JSON.parse(entry.value) as RecoveryCopy;
          if (
            !copies.some(
              (item) => item.key === copy.key && item.value === copy.value,
            )
          )
            copies.push({ ...copy, id });
        } catch {
          // 非法恢复内容保留原记录
        }
      }
      return copies;
    },
    issues: () =>
      [...entries]
        .filter(([, entry]) => entry.error)
        .map(([key, entry]) => ({ key, ...entry })),
    pending: () => [...entries.values()].some((entry) => entry.pending),
    warning: () => localError,
    dispose: () => clearTimeout(timer),
  };
}
