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
/** 同阶段草稿全部收尾后才报告失败，避免恢复副本遗漏较晚完成的输入 */
export const flushDrafts = async () => {
  for (const final of [false, true]) {
    const results = await Promise.allSettled(
      [...pending.values()]
        .filter((entry) => entry.final === final)
        .map(async (entry) => entry.flush()),
    );
    const failure = results.find((result) => result.status === "rejected");
    if (failure) throw failure.reason;
  }
};
