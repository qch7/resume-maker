import type { Resume } from "../../shared/types/index.ts";
import { newDocument } from "./document.ts";

/** 保存基本信息时沿用服务器的其他栏目和固定引用，避免顺带提交尚未确认的草稿。 */
export function personalComposition(draft: Resume, saved?: Resume): Resume {
  if (draft.id && !saved)
    throw new Error("当前方案已不存在，请刷新后重新选择。");
  const baseline = saved ?? { ...draft, items: [], document: newDocument() };
  return {
    ...baseline,
    id: draft.id,
    version: draft.version,
    template_id: null,
    document: {
      ...(baseline.document ?? newDocument()),
      personal: draft.document?.personal ?? newDocument().personal,
    },
  };
}
