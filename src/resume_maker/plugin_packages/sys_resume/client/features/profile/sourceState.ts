import type {
  CustomInfoField,
  ResumeSection,
} from "@resume-maker/plugin-sdk/shared/types/index";

export interface SourceItem {
  id: string;
  version: string;
  title: string;
  subtitle: string;
  period: string;
  details: string;
  custom_fields: CustomInfoField[];
}

/** 选择资料只追加草稿，重复来源和容量不足时保留原栏目 */
export function addSource(
  section: ResumeSection,
  provider: string,
  item: SourceItem,
  entryId: string,
) {
  if (section.kind === "projects")
    throw new Error("项目栏目使用固定经历版本。");
  if (section.entries.length >= 100)
    throw new Error("栏目已达到一百条资料上限。");
  if (
    section.entries.some(
      (entry) =>
        entry.source?.provider === provider && entry.source.id === item.id,
    )
  )
    throw new Error("这条资料已加入当前栏目。");
  const { id, version, ...copy } = structuredClone(item);
  return {
    ...section,
    entries: [
      ...section.entries,
      {
        ...copy,
        id: entryId,
        visible: true,
        hidden_fields: [],
        source: { provider, id, version },
      },
    ],
  };
}
