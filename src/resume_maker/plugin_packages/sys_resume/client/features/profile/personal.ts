import type { Resume } from "@resume-maker/plugin-sdk/shared/types/index";
import { newDocument } from "@resume-maker/plugin-sdk/shared/resume/document";

/** 保存基本信息时保留服务器上的其他栏目和固定引用 */
export function personalComposition(draft: Resume, saved?: Resume): Resume {
  if (draft.id && !saved)
    throw new Error("当前方案已不存在，请刷新后重新选择。");
  const baseline = saved ?? { ...draft, items: [], document: newDocument() };
  return {
    ...baseline,
    id: draft.id,
    version: draft.version,
    template_id: draft.template_id,
    document: {
      ...(baseline.document ?? newDocument()),
      personal: draft.document?.personal ?? newDocument().personal,
    },
  };
}
