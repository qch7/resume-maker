/** 优先恢复正在执行的计划，过期准备仍须保留取消入口 */
export function recoverActivePlan<
  T extends { state?: string; expires_at?: number },
>(operations: readonly T[]): T | undefined {
  const ordered = [...operations].sort(
    (a, b) => (b.expires_at ?? 0) - (a.expires_at ?? 0),
  );
  const active = ordered.find((item) =>
    [
      "preparing",
      "validating",
      "restart-required",
      "booting",
      "applying",
    ].includes(item.state ?? ""),
  );
  return active ?? (ordered[0]?.state === "planned" ? ordered[0] : undefined);
}
