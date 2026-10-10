export interface CapabilityPlugin {
  id: string;
  title: string;
  required: boolean;
  scope?: string;
  capability_groups?: { id: string; title: string }[];
}

/** 按清单分类聚合完整成员，搜索只影响显示，不缩小整组开关范围 */
export function capabilityGroups<T extends CapabilityPlugin>(
  plugins: T[],
  selected: string[],
  query: string,
) {
  const groups = new Map<string, { id: string; title: string; members: T[] }>();
  for (const item of plugins) {
    const categories = item.capability_groups?.length
      ? item.capability_groups
      : [{ id: "uncategorized", title: "未分类" }];
    for (const category of categories) {
      const group = groups.get(category.id) ?? { ...category, members: [] };
      if (!group.members.some((member) => member.id === item.id))
        group.members.push(item);
      groups.set(category.id, group);
    }
  }
  const search = query.trim().toLocaleLowerCase();
  return [...groups.values()]
    .map((group) => {
      const optional = group.members.filter(
        (item) => !item.required && item.scope !== "task",
      );
      const count = optional.filter((item) =>
        selected.includes(item.id),
      ).length;
      return {
        ...group,
        required: false,
        items: group.members.filter((item) =>
          `${group.title} ${item.title} ${item.id}`
            .toLocaleLowerCase()
            .includes(search),
        ),
        selection: {
          checked: (count === 0
            ? false
            : count === optional.length
              ? true
              : "mixed") as boolean | "mixed",
          count,
          total: optional.length,
        },
      };
    })
    .filter((group) => group.items.length > 0);
}
