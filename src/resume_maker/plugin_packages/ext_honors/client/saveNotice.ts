/** 按保存事务中的关联数描述生效范围，当前草稿单独说明 */
export function honorSaveNotice(
  count: number | null | undefined,
  currentDraft: boolean,
) {
  if (count && count > 0)
    return `已保存到荣誉库，${count} 份关联简历会自动使用最新资料。`;
  return currentDraft
    ? "已保存到荣誉库，已更新当前简历草稿。"
    : "已保存到荣誉库。";
}
