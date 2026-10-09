import {
  restoreDraft,
  type DraftEnvelope,
} from "@resume-maker/plugin-sdk/shared/lib/mergeDraft";
import type { Project } from "@resume-maker/plugin-sdk/shared/types/index";

export interface SourcesForm {
  name: string;
  paths: string;
}

/** 编辑目录保留原始换行，提交时再转换为路径列表 */
export function sourcesForm(project: Project): SourcesForm {
  return { name: project.name, paths: project.roots.join("\n") };
}

/** 旧目录文本缺少读取基线，不把未保存输入默认为最新配置 */
export function restoreSources(
  cached: unknown,
  latest: SourcesForm,
): DraftEnvelope<SourcesForm> {
  return restoreDraft(
    typeof cached === "string"
      ? { ...latest, paths: cached }
      : (cached as SourcesForm | DraftEnvelope<SourcesForm> | null),
    latest,
  );
}

/** 仅在正式提交时去除空行和路径两端空格 */
export function sourcePaths(paths: string) {
  return paths
    .split("\n")
    .map((path) => path.trim())
    .filter(Boolean);
}
