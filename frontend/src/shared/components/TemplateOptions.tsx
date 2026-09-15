import type { Template } from "../types";

/** 为导出排版和模板工作区提供一致的内置版式与已保存模板选项。 */
export default function TemplateOptions({
  templates,
}: {
  templates: Template[];
}) {
  return (
    <>
      <option value="">内置 · 完整简历</option>
      {templates.map(
        /* 导入模板按相同顺序和名称出现在两个入口。 */ (template) => (
          <option key={template.id} value={template.id}>
            {template.name}
          </option>
        ),
      )}
    </>
  );
}
