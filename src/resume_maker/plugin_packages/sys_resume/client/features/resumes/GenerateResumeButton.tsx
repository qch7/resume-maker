import { FileDown } from "lucide-react";

interface Props {
  exporting: boolean;
  disabled: boolean;
  title?: string;
  guide?: string;
  onGenerate: () => void;
}

/** 在现有工具栏或方案面板中调用同一简历生成流程 */
export default function GenerateResumeButton(props: Props) {
  return (
    <button
      className="primary"
      data-guide={props.guide}
      disabled={props.disabled || props.exporting}
      title={props.title}
      onClick={props.onGenerate}
    >
      <FileDown size={15} />
      {props.exporting ? "正在生成简历…" : "生成简历"}
    </button>
  );
}
