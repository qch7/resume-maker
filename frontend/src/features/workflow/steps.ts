export type GuideTarget =
  | "template-select"
  | "personal-basic"
  | "personal-education"
  | "personal-skills"
  | "projects"
  | "analysis"
  | "experience-save"
  | "experience-use"
  | "honor-recognize"
  | "honor-select"
  | "structure"
  | "composition-save"
  | "export";

export interface GuideAction {
  text: string;
  action: string;
  target: GuideTarget;
  projectId?: string;
}

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
    title: "模板识别",
    detail: "识别模板 · 确认版式",
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
    detail: "导入项目 · AI 整理",
    target: "experience-save",
    substeps: [
      { title: "导入项目", target: "projects" },
      { title: "智能整理", target: "analysis" },
    ],
  },
  {
    title: "荣誉证书",
    detail: "识别证书 · 筛选荣誉",
    target: "honor-recognize",
    substeps: [
      { title: "识别荣誉", target: "honor-recognize" },
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
