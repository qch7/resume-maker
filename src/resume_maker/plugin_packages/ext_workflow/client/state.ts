import type { HonorSource } from "@resume-maker/plugin-sdk/shared/types/honors";
import { getProjectWorkflow } from "./projectState.ts";
import { getProfileProgress } from "@resume-maker/plugin-sdk/shared/resume/progress";
import { WORKFLOW_STEPS, type GuideAction } from "./steps.ts";
import { workflowReadiness } from "./readiness.ts";
export type { GuideTarget } from "./steps";

/** 汇总模板、个人资料、项目、荣誉、编排及导出的独立准备进度 */
export function getWorkflow(
  input: Parameters<typeof getProjectWorkflow>[0] & {
    honors?: HonorSource[];
  },
) {
  const project = getProjectWorkflow(input);
  const profile = getProfileProgress(input.draft.document);
  // 完整资料默认使用内置版式，空模板 ID 不代表缺少可用模板
  const templateReady = !!input.draft.template_id || !!input.draft.document;
  const personalReady = profile.basic && profile.education && profile.skills;
  const honorRecognized =
    profile.selectedHonor ||
    !!input.honors?.some(
      /* 已核对的来源可直接进入筛选 */ (honor) =>
        honor.reviewed && !!honor.fields.name.trim(),
    );
  const completed = [
    templateReady,
    personalReady,
    project.done[1] && project.step !== 1,
    profile.selectedHonor,
    project.done[2],
    templateReady && project.done[3],
  ];
  const statuses = workflowReadiness(input, completed);
  const done = statuses.map(
    (status) => status === "complete" || status === "ready",
  );
  const personalTarget = !profile.basic
    ? "personal-basic"
    : !profile.education
      ? "personal-education"
      : "personal-skills";
  const guides: GuideAction[] = [
    templateReady
      ? {
          text: input.draft.template_id
            ? "模板已用于当前简历，接下来填写个人资料。"
            : "已选择内置完整简历，可直接填写资料，也可导入自己的模板。",
          action: "填写资料",
          target: "personal-basic",
        }
      : {
          text: "导入模板并核对识别结果，或从模板库选择内置版式，再用于当前简历。",
          action: "识别模板",
          target: "template-select",
        },
    personalReady
      ? {
          text: "基本信息、教育经历与专业技能已填写，项目和荣誉可通过后续步骤补充。",
          action: "整理项目",
          target: "experience-save",
        }
      : {
          text: !profile.basic
            ? "填写姓名和至少一种联系方式，再补充教育经历与专业技能；项目和荣誉可跳转到对应步骤。"
            : !profile.education
              ? "补充学校、专业和在校时间；项目经历与荣誉证书可在对应步骤整理。"
              : "补充专业技能，突出与求职岗位相关的能力。",
          action: "完善资料",
          target: personalTarget,
        },
    !input.projectCount
      ? {
          text: "项目经历为可选栏目，可新建手工项目或导入源码；也可继续编排并导出当前资料。",
          action: "添加项目（可选）",
          target: "projects",
        }
      : project.step < 2
        ? project.target === "analysis" && !input.analyzing
          ? {
              text: "项目经历为可选栏目。可手工填写描述、亮点，再保存并用于当前简历；源码分析可按需使用。",
              action: "编辑经历",
              target: "experience-save",
            }
          : project
        : {
            text: "经历版本已保存，可继续选择荣誉，或在简历编排时调整引用版本及亮点。",
            action: "选择荣誉",
            target: "honor-select",
          },
    statuses[3] === "optional"
      ? {
          text: honorRecognized
            ? "荣誉为可选栏目，可从已核对的资料中选择条目；也可继续编排当前简历。"
            : "荣誉为可选栏目，可手动录入或识别证书；也可继续编排当前简历。",
          action: "继续编排（荣誉可跳过）",
          target: "structure",
        }
      : {
          text: profile.selectedHonor
            ? "荣誉已加入当前简历，可继续调整栏目顺序与展示内容。"
            : "荣誉栏目已跳过，可继续编排。需要添加荣誉时，可在栏目编排中重新显示。",
          action: "编排简历",
          target: "structure",
        },
    project.step === 2
      ? project
      : {
          text: "调整栏目顺序、项目亮点及内容显隐，确认预览后点击“保存简历方案”。",
          action: "保存简历方案",
          target: "composition-save",
        },
    project.step === 3 && templateReady
      ? project
      : {
          text: "在当前简历中确认模板和内容，点击生成简历后下载 Word、可用的 PDF。",
          action: "生成简历",
          target: "export",
        },
  ];
  const substeps = [
    [],
    [profile.basic, profile.education, done[2], done[3], profile.skills],
    [project.done[0], done[2]],
    [honorRecognized, profile.selectedHonor],
    [],
    [],
  ];
  const pending = statuses.findIndex(
    /* 可选及已隐藏栏目不阻碍下一项必需操作 */ (status) => status === "pending",
  );
  const step = pending < 0 ? WORKFLOW_STEPS.length - 1 : pending;
  // 已保存方案仍需提示当前项目的旧版本引用
  const needsReference =
    step === 5 &&
    project.step === 2 &&
    input.draft.items.some(
      (item) => item.project_id === input.detail?.project.id,
    );
  const recommendation = needsReference ? project : guides[step];
  return {
    done,
    statuses,
    step: needsReference ? 4 : step,
    guides,
    substeps,
    text: recommendation.text,
    action: recommendation.action,
    target: recommendation.target,
    projectId: recommendation.projectId,
  };
}
