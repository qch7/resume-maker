/** 优先恢复正在执行的计划，过期准备仍须保留取消入口 */
export function recoverActivePlan<
  T extends { state?: string; expires_at?: number },
>(operations: readonly T[]): T | undefined {
  const active = operations.filter((item) =>
    [
      "preparing",
      "validating",
      "restart-required",
      "booting",
      "applying",
    ].includes(item.state ?? ""),
  );
  const candidates = active.length
    ? active
    : operations.filter((item) => item.state === "planned");
  return candidates.sort(
    (a, b) => (b.expires_at ?? 0) - (a.expires_at ?? 0),
  )[0];
}
