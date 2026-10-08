export interface DraftEnvelope<T> {
  value: T;
  baseline: T | null;
}

/** 恢复带基线的表单，旧缓存缺少基线时等待用户核对 */
export function restoreDraft<T>(
  cached: T | DraftEnvelope<T> | null,
  latest: T,
): DraftEnvelope<T> {
  if (record(cached) && "value" in cached && "baseline" in cached)
    return cached as unknown as DraftEnvelope<T>;
  return {
    value: (cached ?? latest) as T,
    baseline: cached === null || equal(cached, latest) ? latest : null,
  };
}

/** 三方合并保留单边修改，双方冲突沿用本页输入并报告待核对位置 */
export function mergeDraft<T>(baseline: T, local: T, latest: T) {
  const conflicts: string[] = [];
  /** 递归合并字段和稳定标识列表，不改变三份原始输入 */
  function merge(
    base: unknown,
    ours: unknown,
    theirs: unknown,
    path: string,
  ): unknown {
    if (equal(ours, base)) return structuredClone(theirs);
    if (equal(theirs, base) || equal(ours, theirs))
      return structuredClone(ours);
    if (record(base) && record(ours) && record(theirs)) {
      const value: Record<string, unknown> = {};
      for (const key of new Set([
        ...Object.keys(base),
        ...Object.keys(ours),
        ...Object.keys(theirs),
      ])) {
        const merged = merge(
          base[key],
          ours[key],
          theirs[key],
          path ? `${path}.${key}` : key,
        );
        if (merged !== undefined) value[key] = merged;
      }
      return value;
    }
    if (identified(base) && identified(ours) && identified(theirs)) {
      const b = new Map(base.map((item) => [item.id, item]));
      const o = new Map(ours.map((item) => [item.id, item]));
      const t = new Map(theirs.map((item) => [item.id, item]));
      const localOrder = ours.map((item) => item.id);
      const remoteOrder = theirs.map((item) => item.id);
      const baseOrder = base.map((item) => item.id);
      const order = equal(localOrder, baseOrder) ? remoteOrder : localOrder;
      if (
        !equal(localOrder, baseOrder) &&
        !equal(remoteOrder, baseOrder) &&
        !equal(localOrder, remoteOrder)
      )
        conflicts.push(`${path}.顺序`);
      return [
        ...new Set([...order, ...localOrder, ...remoteOrder, ...baseOrder]),
      ]
        .map((id) => merge(b.get(id), o.get(id), t.get(id), `${path}.${id}`))
        .filter((item) => item !== undefined);
    }
    conflicts.push(path);
    return structuredClone(ours);
  }
  return { value: merge(baseline, local, latest, "") as T, conflicts };
}

/** JSON 表单按实际值比较，缺失字段和显式空值分别处理 */
export function equal(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b))
    return (
      a.length === b.length && a.every((value, index) => equal(value, b[index]))
    );
  if (record(a) && record(b))
    return (
      Object.keys(a).length === Object.keys(b).length &&
      Object.keys(a).every(
        (key) => Object.hasOwn(b, key) && equal(a[key], b[key]),
      )
    );
  return false;
}

/** 保存确认只接纳本次提交，后续输入仍基于返回的正式资料继续编辑 */
export function acceptDraftConfirmation<T>(
  current: T,
  submitted: T,
  saved: T,
): DraftEnvelope<T> {
  return {
    value: mergeDraft(submitted, current, saved).value,
    baseline: saved,
  };
}

/** 仅对象字段参与递归，数组另按稳定标识合并 */
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** 栏目和字段列表以唯一标识合并，普通列表保留整份选择 */
function identified(
  value: unknown,
): value is (Record<string, unknown> & { id: string })[] {
  return (
    Array.isArray(value) &&
    value.every((item) => record(item) && typeof item.id === "string") &&
    new Set(value.map((item) => item.id)).size === value.length
  );
}
