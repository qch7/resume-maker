/** 兼容旧单份副本并保留每次不同的输入，重复载入不丢失先前原稿 */
export function recoveryCopies<T>(previous: T | T[] | null, addition?: T): T[] {
  const copies =
    previous === null ? [] : Array.isArray(previous) ? previous : [previous];
  return addition === undefined ||
    copies.some((copy) => JSON.stringify(copy) === JSON.stringify(addition))
    ? copies
    : [...copies, addition];
}
