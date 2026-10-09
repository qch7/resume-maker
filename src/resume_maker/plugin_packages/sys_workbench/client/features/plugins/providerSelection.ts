interface ProviderPlugin {
  id: string;
  required: boolean;
  provided?: Record<string, Record<string, { cardinality?: string }>>;
}

interface ProviderInstance {
  id: string;
  plugin: string;
  bindings: Record<string, Record<string, string>>;
}

/** 新提供方的全部唯一能力一起替换，显式绑定同步进入同一候选计划 */
export function replaceProvider(
  plugins: ProviderPlugin[],
  selected: string[],
  instances: ProviderInstance[],
  provider: string,
) {
  const candidate = plugins.find((item) => item.id === provider);
  if (!candidate) throw new Error("提供方尚未安装，请刷新插件列表。");
  const conflicts = new Map<string, Set<string>>();
  for (const [domain, services] of Object.entries(candidate.provided ?? {})) {
    for (const [name, spec] of Object.entries(services)) {
      for (const item of plugins) {
        const existing = item.provided?.[domain]?.[name];
        if (
          item.id !== provider &&
          selected.includes(item.id) &&
          existing &&
          (spec.cardinality !== "many" || existing.cardinality !== "many")
        ) {
          if (item.required)
            throw new Error("此操作会停用必需提供方，请保留基础能力。");
          const keys = conflicts.get(item.id) ?? new Set<string>();
          keys.add(`${domain}/${name}`);
          conflicts.set(item.id, keys);
        }
      }
    }
  }
  return {
    selected: [
      ...selected.filter((id) => !conflicts.has(id) && id !== provider),
      provider,
    ],
    removed: [...conflicts.keys()],
    instances: instances.map((instance) => ({
      ...instance,
      bindings: Object.fromEntries(
        Object.entries(instance.bindings).map(([domain, bindings]) => [
          domain,
          Object.fromEntries(
            Object.entries(bindings).map(([name, owner]) => [
              name,
              conflicts
                .get(owner)
                ?.has(`${domain === "remote" ? "host" : domain}/${name}`)
                ? provider
                : owner,
            ]),
          ),
        ]),
      ),
    })),
  };
}

/** 集合能力保留原有选择，唯一能力才显示替换入口 */
export function providerChoices(plugins: ProviderPlugin[]) {
  const groups = new Map<
    string,
    { domain: string; name: string; ids: string[] }
  >();
  for (const item of plugins) {
    for (const [domain, services] of Object.entries(item.provided ?? {})) {
      for (const [name, spec] of Object.entries(services)) {
        if (spec.cardinality === "many") continue;
        const key = `${domain}/${name}`;
        const group = groups.get(key) ?? { domain, name, ids: [] };
        group.ids.push(item.id);
        groups.set(key, group);
      }
    }
  }
  return [...groups.values()].filter((group) => group.ids.length > 1);
}

/** 多包候选先拒绝互相冲突，避免按添加顺序选择唯一提供方 */
export function replaceProviders(
  plugins: ProviderPlugin[],
  selected: string[],
  instances: ProviderInstance[],
  providers: string[],
) {
  const enabled = plugins.filter((item) => providers.includes(item.id));
  for (let index = 0; index < enabled.length; index++) {
    for (const [domain, services] of Object.entries(
      enabled[index].provided ?? {},
    )) {
      for (const [name, spec] of Object.entries(services)) {
        if (
          enabled.slice(index + 1).some((item) => {
            const other = item.provided?.[domain]?.[name];
            return (
              other &&
              (spec.cardinality !== "many" || other.cardinality !== "many")
            );
          })
        )
          throw new Error(
            `候选包在 ${domain}/${name} 存在唯一能力冲突，请只选择一个提供方。`,
          );
      }
    }
  }
  let result = { selected, instances, removed: [] as string[] };
  for (const id of providers)
    result = replaceProvider(plugins, result.selected, result.instances, id);
  return result;
}
