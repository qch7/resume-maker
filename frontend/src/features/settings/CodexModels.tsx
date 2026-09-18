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
    description: "从 PDF 或证书图片提取荣誉资料（需支持图片的模型）",
  },
  {
    id: "connection_check",
    title: "连接测试",
    description: "测试实际连接",
  },
];

const efforts: { value: ReasoningEffort; label: string }[] = [
  { value: "minimal", label: "最低 · minimal" },
  { value: "low", label: "低 · low" },
  { value: "medium", label: "中 · medium" },
  { value: "high", label: "高 · high" },
  { value: "xhigh", label: "最高 · xhigh" },
];

interface FieldsProps {
  title: string;
  value: AISettings;
  inheritedModel: string;
  inheritedEffort: string;
  disabled: boolean;
  onChange: (value: AISettings) => void;
}

/** 复用模型输入与思考强度选择；空值明确显示其继承来源 */
function ModelFields(props: FieldsProps) {
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
        <select
          aria-label={`${props.title}思考强度`}
          value={props.value.reasoning_effort}
          disabled={props.disabled}
          onChange={
            /* 选择受支持的强度；空值恢复继承 */ (event) =>
              props.onChange({
                ...props.value,
                reasoning_effort: event.target.value as ReasoningEffort,
              })
          }
        >
          <option value="">{props.inheritedEffort}</option>
          {efforts.map(
            /* 显示与 CLI 参数一一对应的强度选项 */ (effort) => (
              <option key={effort.value} value={effort.value}>
                {effort.label}
              </option>
            ),
          )}
        </select>
      </label>
    </>
  );
}

/** 编辑全局默认和各 AI 功能覆盖；模型与强度可分别继承 */
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
        模型填写当前 Provider 支持的模型 ID；留空时继承 CLI / Profile 配置。
        思考强度需由所选模型支持，强度越高通常耗时越长。
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
      <p className="subtle">
        每项可单独设置模型和思考强度，留空则继承全局默认。保存后用于新提交的任务，
        模板自动修正的每一轮均使用该功能的设置。
      </p>
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
                  /* 只更新当前功能；保留其他覆盖和 CLI 连接设置 */ (value) =>
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
