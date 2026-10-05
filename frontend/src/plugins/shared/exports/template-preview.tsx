import DocumentPreview from "../../DocumentPreview";
import type { WordPreviewProps } from "../../slots";

/** 模板页面通过文档预览贡献选择渲染器，未安装 Word 时显示公开回退结果 */
export default function TemplatePreview(props: WordPreviewProps) {
  return <DocumentPreview format="resume/v1" {...props} />;
}
