import type { ClientDescriptor } from "../shared/lib/capabilities";
import type { ClientExtensionPoints, WorkflowStep } from "./extensions";

/** 旧插件的贡献名称映射到当前实例，已经使用实例名称的贡献保持原样 */
export function instanceIdentifier(
  item: Pick<ClientDescriptor, "id" | "plugin">,
  id: string,
) {
  const plugin = item.plugin ?? item.id;
  return plugin !== item.id && id.startsWith(plugin + "/")
    ? item.id + id.slice(plugin.length)
    : id;
}

/** 清单和注册调用使用同一身份规则，两个实例不能占用彼此的页面和字段 */
export function instanceDescriptor(item: ClientDescriptor): ClientDescriptor {
  return {
    ...item,
    contributes: Object.fromEntries(
      Object.entries(item.contributes ?? {}).map(([point, ids]) => [
        point,
        ids.map((id) => instanceIdentifier(item, id)),
      ]),
    ),
  };
}

/** 工作流步骤引用本插件的命令和状态时一起切换到当前实例 */
export function instanceContribution<K extends keyof ClientExtensionPoints>(
  item: ClientDescriptor,
  point: K,
  value: ClientExtensionPoints[K],
): ClientExtensionPoints[K] {
  if (point !== "workflow.steps") return value;
  const step = value as WorkflowStep;
  return {
    ...step,
    state: instanceIdentifier(item, step.state),
    command: instanceIdentifier(item, step.command),
  } as ClientExtensionPoints[K];
}
