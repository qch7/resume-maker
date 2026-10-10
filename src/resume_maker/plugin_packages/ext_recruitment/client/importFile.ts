/** 文件选择和拖放共用校验，拒绝多文件、非 JSON、超限及空白内容 */
export async function readImportFile(files: File[]) {
  if (!files.length) return null;
  if (files.length !== 1) throw new Error("每次只能导入一个文件。");
  const file = files[0];
  if (!file.name.toLowerCase().endsWith(".json"))
    throw new Error("请选择 JSON 文件。");
  if (file.size > 8_000_000) throw new Error("文件超过 8 MB。");
  const content = await file.text();
  if (!content.trim()) throw new Error("文件为空。");
  return { name: file.name, content };
}
