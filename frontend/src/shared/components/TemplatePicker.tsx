import { pluginOptionalComponent } from "../../plugins/runtime";
import type { TemplatePickerProps } from "../../plugins/slots";

/** 通用模板选择插槽在缺少资料库时保留当前引用及明确的内置版式选择 */
export default function TemplatePicker(props: TemplatePickerProps) {
  const Picker = pluginOptionalComponent("templatePicker");
  if (Picker) return <Picker {...props} />;
  return (
    <div className="template-library-picker">
      <span>{props.label}</span>
      <p>
        {props.placeholder ??
          (props.value ? "模板库未启用，当前模板仍保留。" : "内置 · 完整简历")}
      </p>
      {props.value && (
        <button disabled={props.disabled} onClick={() => props.onChange("")}>
          明确改用内置版式
        </button>
      )}
    </div>
  );
}
