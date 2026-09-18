import type { Resume, ResumeDocument } from "../../shared/types/index.ts";
import type { HonorSource } from "../../shared/types/honors.ts";
import { HONOR_FIELDS } from "./fields.ts";
import { updateHonorField } from "./entry.ts";

/** 按来源标识读取已核对荣誉；补齐旧条目并保留每份简历自己的排版设置 */
export function syncHonorDocument(
  document: ResumeDocument | null,
  honors: HonorSource[],
): ResumeDocument | null {
  if (!document) return document;
  const sources = new Map(
    honors
      .filter(/* 未核对的识别建议不能进入简历 */ (honor) => honor.reviewed)
      .map(
        /* 不按可能重复的名称关联 */ (honor) => [`honor:${honor.id}`, honor],
      ),
  );
  let changed = false;
  const sections = document.sections.map(
    /* 同步内容不改变栏目和条目的排列 */ (section) => {
      let sectionChanged = false;
      const entries = section.entries.map(
        /* 手动录入、删除来源和同名荣誉各自保持原内容 */ (entry) => {
          const source = sources.get(entry.id);
          if (!source) return entry;
          let synced = entry;
          for (const field of HONOR_FIELDS)
            synced = updateHonorField(synced, field.key, {
              value: source.fields[field.key],
            });
          if (JSON.stringify(synced) === JSON.stringify(entry)) return entry;
          sectionChanged = true;
          return synced;
        },
      );
      if (!sectionChanged) return section;
      changed = true;
      return { ...section, entries };
    },
  );
  return changed ? { ...document, sections } : document;
}

/** 当前和缓存方案使用同一同步规则；其他未保存草稿及版本号保持不变 */
export function syncHonorResume(resume: Resume, honors: HonorSource[]): Resume {
  const document = syncHonorDocument(resume.document, honors);
  return document === resume.document ? resume : { ...resume, document };
}
