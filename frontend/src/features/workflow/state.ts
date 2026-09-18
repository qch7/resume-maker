import type { HonorSource } from "../../shared/types/honors";
import { getProjectWorkflow } from "./projectState.ts";
import { getProfileProgress } from "./profile.ts";
import { WORKFLOW_STEPS, type GuideAction } from "./steps.ts";
export type { GuideTarget } from "./steps";

/** 汇总模板、个人资料、项目、荣誉、编排及导出的独立准备进度 */
export function getWorkflow(
  input: Parameters<typeof getProjectWorkflow>[0] & {
    honors?: HonorSource[];
  },
) {
  const project = getProjectWorkflow(input);
  const profile = getProfileProgress(input.draft.document);
  // 完整资料默认使用内置版式；空模板 ID 不代表缺少可用模板
  const templateReady = !!input.draft.template_id || !!input.draft.document;
  const personalReady = profile.basic && profile.education && profile.skills;
  const honorRecognized =
    profile.selectedHonor ||
    !!input.honors?.some(
      /* 已核对的来源可直接进入筛选且不把上传或排队当作识别完成 */ (honor) =>
        honor.reviewed && !!honor.fields.name.trim(),
    );
  const done = [
    templateReady,
    personalReady,
    project.done[1] && project.step !== 1,
    profile.honors,
    project.done[2],
    templateReady && project.done[3],
  ];
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
            : "当前使用内置完整简历，可直接填写资料，也可导入模板并识别版式。",
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
    project.step < 2
      ? project
      : {
          text: "项目经历已整理并保存，可继续选择荣誉，或在组合编排时调整引用版本与亮点。",
          action: "选择荣誉",
          target: "honor-select",
        },
    profile.honors
      ? {
          text: profile.selectedHonor
            ? "荣誉已加入当前简历，可继续调整栏目顺序与展示内容。"
            : "当前未展示荣誉栏目，可直接进入组合编排；需要时仍可识别和添加荣誉。",
          action: "编排简历",
          target: "structure",
        }
      : {
          text: honorRecognized
            ? "从已核对的荣誉中选择适合本次求职的条目，加入当前简历。"
            : "上传证书图片或 PDF，识别并核对荣誉资料，再选择加入当前简历；也可手动录入。",
          action: honorRecognized ? "选择荣誉" : "识别荣誉",
          target: honorRecognized ? "honor-select" : "honor-recognize",
        },
    project.step === 2
      ? project
      : {
          text: "调整栏目顺序、项目亮点与内容显隐，确认预览后保存这份简历组合。",
          action: "保存组合",
          target: "composition-save",
        },
    project.step === 3 && templateReady
      ? project
      : {
          text: "在导出面板确认模板和当前内容，生成 Word 后预览排版并下载文件。",
          action: "简历导出",
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
  const pending = done.findIndex(
    /* 下一步按整份简历流程推荐；用户仍可自由跳转 */ (ready) => !ready,
  );
  const step = pending < 0 ? WORKFLOW_STEPS.length - 1 : pending;
  // 引用旧版本和未加入组合属于编排提醒且不能被已保存的组合状态掩盖
  const recommendation =
    step === 5 && project.step === 2 ? project : guides[step];
  return {
    done,
    step: step === 5 && project.step === 2 ? 4 : step,
    guides,
    substeps,
    text: recommendation.text,
    action: recommendation.action,
    target: recommendation.target,
    projectId: recommendation.projectId,
  };
}
