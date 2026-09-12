import { ArrowRight, Check, ChevronDown, ChevronUp } from "lucide-react";
import { getWorkflow, type GuideTarget } from "./state";

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

/** 展示当前制作步骤和下一步操作，支持折叠与目标定位。 */
export default function Workflow({
  value,
  onNavigate,
  collapsed,
  onToggle,
}: {
  value: ReturnType<typeof getWorkflow>;
  onNavigate: (target: GuideTarget, projectId?: string) => void;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const completed = value.done.filter(Boolean).length;
  return (
    <section
      className={`workflow ${collapsed ? "collapsed" : ""}`}
      aria-label="简历制作指引"
    >
      <div className="workflow-overview">
        <strong>制作指引</strong>
        <span>{completed} / 4 项已就绪</span>
        <progress value={completed} max={4} aria-label="简历制作完成进度" />
      </div>
      <div className="workflow-main">
        <ol className="workflow-steps" hidden={collapsed}>
          {steps.map(
            /* 按稳定标识生成对应的列表条目。 */ (step, index) => (
              <li
                key={step.title}
                className={`${value.done[index] ? "complete" : ""} ${index === value.step ? "current" : ""}`}
              >
                <button
                  aria-current={index === value.step ? "step" : undefined}
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      onNavigate(step.target)
                  }
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
            ),
          )}
        </ol>
        <div className="workflow-next">
          <p role="status">{value.text}</p>
          <button
            className="text-button"
            onClick={
              /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                onNavigate(value.target, value.projectId)
            }
          >
            {value.action}
            <ArrowRight size={14} />
          </button>
        </div>
      </div>
      <button
        className="icon-button workflow-toggle"
        aria-label={collapsed ? "展开制作指引" : "收起制作指引"}
        aria-expanded={!collapsed}
        onClick={onToggle}
      >
        {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
    </section>
  );
}
