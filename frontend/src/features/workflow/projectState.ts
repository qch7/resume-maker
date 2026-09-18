import type {
  Experience,
  Export,
  ProjectDetail,
  Resume,
  Revision,
} from "../../shared/types/index";
import { isCurrentExport, sameComposition } from "../resumes/composition.ts";
import { experienceContent } from "../experiences/visibility.ts";

import type { GuideTarget } from "./steps";

/** 判断经历是否包含可使用的描述或完整亮点 */
function hasContent(value?: Experience) {
  return (
    !!value &&
    (!!value.description.trim() ||
      value.highlights.some((h) => h.title.trim() && h.text.trim()))
  );
}

/** 根据草稿、固定引用、模板和导出状态推导可操作的制作步骤 */
export function getProjectWorkflow(input: {
  projectCount: number;
  detail: ProjectDetail | null;
  revisionId: string;
  edited?: boolean;
  draft: Resume;
  saved?: Resume;
  revisions: Record<string, Revision>;
  result: Export | null;
  exporting: boolean;
  analyzing: boolean;
}) {
  const { detail, draft, revisions, result } = input;
  const revision = revisions[input.revisionId];
  const settings =
    draft.document?.project_visibility?.[detail?.project.id ?? ""] ?? {};
  const unsaved =
    input.edited ??
    (!!detail &&
      experienceContent(detail.working.content, settings) !==
        experienceContent(revision?.content, settings));
  const prepared = hasContent(revision?.content) && !unsaved;
  const included = draft.items.find((i) => i.project_id === detail?.project.id);
  const incomplete = draft.items.find(
    (i) =>
      revisions[i.revision_id] && !hasContent(revisions[i.revision_id].content),
  );
  const compositionReady =
    draft.items.length > 0 &&
    draft.items.every((i) => hasContent(revisions[i.revision_id]?.content));
  const compositionSaved =
    compositionReady && sameComposition(input.saved, draft);
  const exported = isCurrentExport(result, draft);
  const done = [
    input.projectCount > 0,
    prepared,
    prepared && compositionSaved,
    prepared && compositionSaved && exported,
  ];

  /** 构建一个带状态、说明和定位目标的制作指引步骤 */
  function guide(
    step: number,
    text: string,
    action: string,
    target: GuideTarget,
    projectId?: string,
  ) {
    return { done, step, text, action, target, projectId };
  }
  if (!input.projectCount)
    return guide(
      0,
      "导入项目目录，从源码整理可复用的项目经历。",
      "导入项目",
      "projects",
    );
  if (!detail || !revision)
    return guide(1, "正在读取项目经历与版本…", "查看经历", "experience-save");
  if (unsaved)
    return guide(
      1,
      "当前项目有未提交的改动。确认后点击“提交为新版本”，再用于当前简历。",
      "去提交修改",
      "experience-save",
    );
  if (!prepared)
    return guide(
      1,
      input.analyzing
        ? "AI 正在整理项目，可在项目会话中查看进展；完成后采用建议并保存。"
        : "先分析项目并采用建议，或手工编辑经历，再保存为版本。",
      "整理项目经历",
      "analysis",
    );
  if (!included)
    return guide(
      2,
      "当前项目经历已保存。点击“用于当前简历”加入组合，再勾选需要的亮点。",
      "去加入简历",
      "experience-use",
    );
  if (included.revision_id !== input.revisionId) {
    const pinned = revisions[included.revision_id];
    return guide(
      2,
      `正在编辑 r${revision.number}，简历仍引用${pinned ? ` r${pinned.number}` : "其他版本"}。如需采用当前内容，点击“用于当前简历”；也可保留原版本。`,
      "查看引用版本",
      "experience-use",
    );
  }
  if (incomplete)
    return guide(
      1,
      "组合中还有空白项目经历，先整理内容，或从右侧移除该项目。",
      "整理空白经历",
      "experience-save",
      incomplete.project_id,
    );
  if (!compositionReady)
    return guide(
      2,
      "正在读取组合中的经历版本…",
      "查看组合",
      "composition-save",
    );
  if (!draft.name.trim())
    return guide(
      2,
      "给这份简历方案填写名称，方便以后继续使用。",
      "完善简历方案",
      "composition-save",
    );
  if (!compositionSaved)
    return guide(
      2,
      "项目和亮点已加入组合。确认顺序后保存组合，固定这份简历使用的版本。",
      "去保存组合",
      "composition-save",
    );
  if (!draft.template_id && !draft.document)
    return guide(
      3,
      "选择 Word 模板，导出时保留模板中的个人信息和其他栏目。",
      "选择模板",
      "template-select",
    );
  if (input.exporting)
    return guide(
      3,
      "正在生成 Word 并计算实际页数，请稍候。",
      "查看导出进展",
      "export",
    );
  if (exported)
    return guide(
      3,
      result?.pages
        ? `当前组合已导出，共 ${result.pages} 页。可下载 Word，或继续调整下一份简历。`
        : "当前组合的 Word 已生成，可在右侧下载；排版预览状态见导出结果。",
      "查看导出结果",
      "export",
    );
  return guide(
    3,
    result
      ? "组合已更新，上次导出仍是旧内容。重新导出即可生成当前版本的 Word。"
      : "组合与模板已就绪。导出 Word 后可查看实际页数并下载文件。",
    "去导出 Word",
    "export",
  );
}
