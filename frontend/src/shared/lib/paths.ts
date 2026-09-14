/** 多来源列表只追加新文件夹，保留已有顺序，并忽略 Windows 路径大小写与尾部分隔符差异。 */
export function appendPath(value: string, selected: string): string {
  /** 仅用于比较目录，不改变用户填写的实际路径文本。 */
  function key(path: string) {
    return path
      .trim()
      .replaceAll("/", "\\")
      .replace(/\\+$/, "")
      .toLocaleLowerCase();
  }
  const paths = value
    .split("\n")
    .map(/* 去除空行和手动粘贴的两端空白。 */ (path) => path.trim())
    .filter(Boolean);
  if (
    paths.some(
      /* 同一个来源目录不能重复添加。 */ (path) => key(path) === key(selected),
    )
  )
    return value;
  return [...paths, selected].join("\n");
}
