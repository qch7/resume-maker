import type { ClientDescriptor } from "../shared/lib/capabilities";

/** 远端集合需要明确提供方，不能由装载顺序隐式抢占 */
export function remoteProvider(
  item: ClientDescriptor,
  name: string,
  owner?: string,
) {
  const binding = item.bindings?.remote[name];
  if (!binding) throw new Error(`未声明远端依赖 ${name}`);
  const selected = owner ?? (!binding.many ? binding.owners[0] : undefined);
  if (!selected || !binding.owners.includes(selected))
    throw new Error(`远端依赖 ${name} 需要选择已绑定的提供方`);
  return selected;
}

/** 服务只按宿主求解的所有者绑定，失败插件不能提供半注册能力 */
export function createClientServices() {
  const values = new Map<string, unknown>();
  /** 实例和服务名共同组成唯一身份 */
  function key(owner: string, name: string) {
    return JSON.stringify([owner, name]);
  }
  return {
    /** 提供方只能注册清单承诺的协议版本 */
    provide(
      item: ClientDescriptor,
      name: string,
      value: unknown,
      version: string,
    ) {
      if (item.provides?.[name]?.version !== version)
        throw new Error(`插件 ${item.id} 未声明客户端能力 ${name}@${version}`);
      const identity = key(item.id, name);
      if (values.has(identity)) throw new Error(`客户端能力重复：${identity}`);
      values.set(identity, value);
      return () => {
        values.delete(identity);
      };
    },
    /** 消费方按显式绑定读取唯一能力或有序集合 */
    require<T>(item: ClientDescriptor, name: string): T {
      const binding = item.bindings?.client[name];
      if (!binding) throw new Error(`插件 ${item.id} 未声明客户端依赖 ${name}`);
      const selected = binding.owners.map((owner) => {
        const identity = key(owner, name);
        if (!values.has(identity))
          throw new Error(`客户端能力尚未激活：${owner}/${name}`);
        return values.get(identity);
      });
      return (binding.many ? Object.freeze(selected) : selected[0]) as T;
    },
    /** 激活完成前核对承诺能力，缺失时由调用方撤销全部注册 */
    validate(item: ClientDescriptor) {
      for (const name of Object.keys(item.provides ?? {}))
        if (!values.has(key(item.id, name)))
          throw new Error(`插件缺少客户端能力：${name}`);
    },
  };
}
