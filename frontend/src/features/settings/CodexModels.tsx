import { useId } from "react";
import type {
  AIFunction,
  AISettings,
  ProviderSettings,
  ReasoningEffort,
} from "../../shared/types/index";

const functions: { id: AIFunction; title: string; description: string }[] = [
  {
    id: "project_analysis",
    title: "项目分析",
    description: "分析项目、重新分析源码",
  },
  {
    id: "conversation",
    title: "普通对话",
    description: "AI 会话中讨论整个项目",
  },
  {
    id: "highlight_edit",
    title: "亮点修改",
    description: "让 AI 修改、针对单条亮点对话",
  },
  {
    id: "template_analysis",
    title: "模板识别",
    description: "Word 模板的 AI 识别及自动修正",
  },
  {
    id: "template_repair",
    title: "模板完善",
    description: "AI 继续完善、按说明调整",
  },
  {
    id: "honor_recognition",
    title: "证书识别",
    description: "提取并整理证书字段",
  },
  {
    id: "connection_check",
    title: "连接测试",
    description: "测试实际连接",
  },
];

const efforts: { value: ReasoningEffort; label: string }[] = [
  { value: "none", label: "关闭 · none" },
  { value: "minimal", label: "最低 · minimal" },
  { value: "low", label: "低 · low" },
  { value: "medium", label: "中 · medium" },
  { value: "high", label: "高 · high" },
  { value: "xhigh", label: "很高 · xhigh" },
  { value: "max", label: "最大 · max" },
  { value: "ultra", label: "极高 · ultra" },
];

interface FieldsProps {
  title: string;
  value: AISettings;
  inheritedModel: string;
  inheritedEffort: string;
  disabled: boolean;
  onChange: (value: AISettings) => void;
}

/** 复用模型和自定义强度输入，空值明确显示其继承来源 */
function ModelFields(props: FieldsProps) {
  const effortOptions = useId();
  return (
    <>
      <label>
        模型
        <input
          aria-label={`${props.title}模型`}
          value={props.value.model}
          placeholder={props.inheritedModel}
          disabled={props.disabled}
          onChange={
            /* 保留强度且仅修改当前功能或默认模型 */ (event) =>
              props.onChange({ ...props.value, model: event.target.value })
          }
        />
      </label>
      <label>
        思考强度
        <input
          aria-label={`${props.title}思考强度`}
          list={effortOptions}
          maxLength={64}
          value={props.value.reasoning_effort}
          placeholder={props.inheritedEffort}
          disabled={props.disabled}
          onChange={
            /* 保留 CLI 支持的自定义强度，空值恢复继承 */ (event) =>
              props.onChange({
                ...props.value,
                reasoning_effort: event.target.value,
              })
          }
        />
        <datalist id={effortOptions}>
          {efforts.map(
            /* 显示和 CLI 参数一一对应的强度选项 */ (effort) => (
              <option key={effort.value} value={effort.value}>
                {effort.label}
              </option>
            ),
          )}
        </datalist>
      </label>
    </>
  );
}

/** 编辑全局默认和各 AI 功能覆盖，模型和强度可分别继承 */
export default function CodexModels(props: {
  value: ProviderSettings;
  disabled: boolean;
  onChange: (value: ProviderSettings) => void;
}) {
  const provider = props.value;
  return (
    <section className="codex-models" aria-label="Codex 模型与思考强度">
      <h3>全局默认</h3>
      <p className="subtle">
        留空继承 CLI / Profile 配置。思考强度可选常见值或填写当前模型支持的值。
      </p>
      <div className="form-grid">
        <ModelFields
          title="全局默认"
          value={provider}
          inheritedModel="继承 CLI / Profile"
          inheritedEffort="继承 CLI / Profile"
          disabled={props.disabled}
          onChange={
            /* 修改默认值时保留各功能的独立覆盖 */ (value) =>
              props.onChange({ ...provider, ...value })
          }
        />
      </div>
      <h3>各 AI 功能</h3>
      <p className="subtle">留空继承全局默认，保存后用于新任务。</p>
      <div className="ai-function-list">
        {functions.map(
          /* 为每个真实 AI 入口提供独立配置 */ (feature) => (
            <div className="ai-function-row" key={feature.id}>
              <div className="ai-function-title">
                <strong>{feature.title}</strong>
                <span className="subtle">{feature.description}</span>
              </div>
              <ModelFields
                title={feature.title}
                value={
                  provider.functions[feature.id] ?? {
                    model: "",
                    reasoning_effort: "",
                  }
                }
                inheritedModel={
                  provider.model.trim()
                    ? `继承：${provider.model.trim()}`
                    : "继承全局默认"
                }
                inheritedEffort={
                  provider.reasoning_effort
                    ? `继承：${provider.reasoning_effort}`
                    : "继承全局默认"
                }
                disabled={props.disabled}
                onChange={
                  /* 只更新当前功能，保留其他覆盖和 CLI 连接设置 */ (value) =>
                    props.onChange({
                      ...provider,
                      functions: { ...provider.functions, [feature.id]: value },
                    })
                }
              />
            </div>
          ),
        )}
      </div>
    </section>
  );
}
