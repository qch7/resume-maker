import { ArrowRight, Check } from "lucide-react";
import { getWorkflow, type GuideTarget } from "./workflowState";

const steps: { title: string; detail: string; target: GuideTarget }[] = [
  { title: "导入项目", detail: "关联本机源码", target: "projects" },
  {
    title: "整理经历",
    detail: "AI 建议 · 编辑保存",
    target: "experience-save",
  },
  { title: "组合简历", detail: "选择项目与亮点", target: "composition-save" },
  { title: "导出 Word", detail: "模板 · 预览 · 下载", target: "export" },
];

export default function Workflow({
  value,
  onNavigate,
}: {
  value: ReturnType<typeof getWorkflow>;
  onNavigate: (target: GuideTarget, projectId?: string) => void;
}) {
  const completed = value.done.filter(Boolean).length;
  return (
    <section className="workflow" aria-label="简历制作指引">
      <div className="workflow-overview">
        <strong>制作指引</strong>
        <span>{completed} / 4 项已就绪</span>
        <progress value={completed} max={4} aria-label="简历制作完成进度" />
      </div>
      <div className="workflow-main">
        <ol className="workflow-steps">
          {steps.map((step, index) => (
            <li
              key={step.title}
              className={`${value.done[index] ? "complete" : ""} ${index === value.step ? "current" : ""}`}
            >
              <button
                aria-current={index === value.step ? "step" : undefined}
                onClick={() => onNavigate(step.target)}
              >
                <span className="step-number">
                  {value.done[index] ? <Check size={15} /> : index + 1}
                </span>
                <span>
                  <strong>{step.title}</strong>
                  <small>{step.detail}</small>
                </span>
              </button>
            </li>
          ))}
        </ol>
        <div className="workflow-next">
          <p role="status">{value.text}</p>
          <button
            className="text-button"
            onClick={() => onNavigate(value.target, value.projectId)}
          >
            {value.action}
            <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}
