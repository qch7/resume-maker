/** 按原顺序追加新目录并在比较时忽略 Windows 路径大小写和末尾分隔符 */
export function appendPath(value: string, selected: string): string {
  /** 仅规范化目录比较值 */
  function key(path: string) {
    return path
      .trim()
      .replaceAll("/", "\\")
      .replace(/\\+$/, "")
      .toLocaleLowerCase();
  }
  const paths = value
    .split("\n")
    .map(/* 去除空行和手动粘贴的两端空白 */ (path) => path.trim())
    .filter(Boolean);
  if (
    paths.some(
      /* 同一个来源目录不能重复添加 */ (path) => key(path) === key(selected),
    )
  )
    return value;
  return [...paths, selected].join("\n");
}
