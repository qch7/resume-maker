const pending = new Map<
  string,
  { flush: () => Promise<void>; final: boolean }
>();
/** 登记离开页面前需要刷新的草稿回调并返回解除登记函数 */
export function registerDraft(
  key: string,
  flush: () => Promise<void>,
  final = false,
) {
  pending.set(key, { flush, final });
  return () => {
    pending.delete(key);
  };
}
/** 等待所有当前登记的草稿写入，任一失败都会阻止后续页面操作 */
export const flushDrafts = async () => {
  await Promise.all(
    [...pending.values()]
      .filter((entry) => !entry.final)
      .map((entry) => entry.flush()),
  );
  await Promise.all(
    [...pending.values()]
      .filter((entry) => entry.final)
      .map((entry) => entry.flush()),
  );
};
