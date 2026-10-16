import type { GuideTarget } from "@resume-maker/plugin-sdk/plugins/slots";
export type {
  GuideTarget,
  GuideAction,
} from "@resume-maker/plugin-sdk/plugins/slots";

export interface GuideSubstep {
  title: string;
  target: GuideTarget;
  jump?: number;
}

export const WORKFLOW_STEPS: {
  title: string;
  detail: string;
  target: GuideTarget;
  substeps: GuideSubstep[];
}[] = [
  {
    title: "模板选择",
    detail: "内置版式 · 导入可选",
    target: "template-select",
    substeps: [],
  },
  {
    title: "个人信息",
    detail: "基本资料 · 教育技能",
    target: "personal-basic",
    substeps: [
      { title: "基本信息", target: "personal-basic" },
      { title: "教育经历", target: "personal-education" },
      { title: "项目经历", target: "experience-save", jump: 3 },
      { title: "荣誉证书", target: "honor-recognize", jump: 4 },
      { title: "专业技能", target: "personal-skills" },
    ],
  },
  {
    title: "项目经历",
    detail: "手工编辑 · 源码分析可选",
    target: "experience-save",
    substeps: [
      { title: "新建项目", target: "projects" },
      { title: "编辑经历", target: "experience-save" },
    ],
  },
  {
    title: "荣誉证书",
    detail: "手动录入 · 证书识别可选",
    target: "honor-recognize",
    substeps: [
      { title: "录入荣誉", target: "honor-recognize" },
      { title: "选择荣誉", target: "honor-select" },
    ],
  },
  {
    title: "组合编排",
    detail: "栏目顺序 · 内容取舍",
    target: "structure",
    substeps: [],
  },
  {
    title: "简历导出",
    detail: "预览排版 · 下载文件",
    target: "export",
    substeps: [],
  },
];
