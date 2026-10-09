import { ArrowRight, Check, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import { getWorkflow, type GuideTarget } from "./state";
import { WORKFLOW_STEPS as steps } from "./steps";

/** 展示当前制作步骤和下一步操作，支持折叠和目标定位 */
export default function Workflow({
  value,
  activeStep,
  onNavigate,
  collapsed,
  onToggle,
}: {
  value: ReturnType<typeof getWorkflow>;
  activeStep: number;
  onNavigate: (target: GuideTarget, projectId?: string) => void;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const completed = value.done.filter(Boolean).length;
  const [selection, setSelection] = useState<{
    step: number;
    target: GuideTarget;
  } | null>(null);
  const current = steps[activeStep];
  const next = collapsed ? value : value.guides[activeStep];
  const activeTarget =
    selection?.step === activeStep
      ? selection.target
      : current.substeps.find(
          /* 默认提示当前大步骤中尚未完成的第一项 */ (_, index) =>
            !value.substeps[activeStep][index],
        )?.target;
  return (
    <section
      className={`workflow ${collapsed ? "collapsed" : ""}`}
      aria-label="简历制作指引"
    >
      <div className="workflow-overview">
        <strong>制作指引</strong>
        <span>
          {completed} / {steps.length} 步已就绪
        </span>
        <progress
          value={completed}
          max={steps.length}
          aria-label="简历制作完成进度"
        />
      </div>
      <div className="workflow-main">
        <ol className="workflow-steps" hidden={collapsed}>
          {steps.map((step, index) => (
            <li
              key={step.title}
              className={`${value.done[index] ? "complete" : ""} ${index === activeStep ? "current" : ""}`}
            >
              <button
                aria-current={index === activeStep ? "step" : undefined}
                aria-label={`第 ${index + 1} 步：${step.title}${value.done[index] ? "，已就绪" : ""}`}
                onClick={
                  /* 大步骤直接导航到工作区并重置子步骤选择 */ () => {
                    setSelection(null);
                    onNavigate(step.target);
                  }
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
          ))}
        </ol>
        {!collapsed && current.substeps.length > 0 && (
          <ol
            className="workflow-substeps"
            aria-label={`${current.title}子步骤`}
          >
            {current.substeps.map(
              /* 子步骤可直接定位表单，跨步骤入口明确显示目的地 */ (
                item,
                index,
              ) => (
                <li key={item.target}>
                  <button
                    className={`${value.substeps[activeStep][index] ? "complete" : ""} ${activeTarget === item.target ? "current" : ""}`}
                    aria-current={
                      activeTarget === item.target ? "step" : undefined
                    }
                    onClick={
                      /* 保留子步骤选择并在工作台保存草稿后导航 */ () => {
                        setSelection({ step: activeStep, target: item.target });
                        onNavigate(item.target);
                      }
                    }
                  >
                    <span className="substep-number">
                      {value.substeps[activeStep][index] ? (
                        <Check size={12} />
                      ) : (
                        index + 1
                      )}
                    </span>
                    {item.title}
                    {item.jump && (
                      <span className="substep-jump">
                        第 {item.jump} 步 <ArrowRight size={12} />
                      </span>
                    )}
                  </button>
                </li>
              ),
            )}
          </ol>
        )}
        <div className="workflow-next">
          <p role="status">{next.text}</p>
          <button
            className="text-button"
            onClick={() => onNavigate(next.target, next.projectId)}
          >
            {next.action}
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
