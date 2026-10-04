import type {
  DefaultField,
  Experience,
  ResumeDocument,
  ResumeItem,
} from "../../shared/types";
import { fieldVisible } from "../experiences/visibility";
import { projectBodyOrder } from "../experiences/bodyOrder";

/** 内容预览遵守显隐和固定引用，不依赖 Word 或远端模型 */
export default function ContentPreview({ input }: { input: string | null }) {
  if (!input) return <p className="subtle">正在读取经历版本…</p>;
  const { document, items } = JSON.parse(input) as {
    document: ResumeDocument;
    items: (ResumeItem & { content: Experience })[];
  };
  const personal = document.personal;
  const sections = document.sections.filter(
    (section) =>
      section.visible &&
      (!section.parent_id ||
        document.sections.find((parent) => parent.id === section.parent_id)
          ?.visible),
  );
  /** 默认字段定义缺席时沿用旧字段，明确移除的字段保持隐藏 */
  function visible(
    key: string,
    hidden: string[],
    definitions?: DefaultField[] | null,
  ) {
    return (
      !hidden.includes(key) &&
      (!definitions || !!definitions.find((field) => field.id === key)?.visible)
    );
  }
  return (
    <article className="content-preview" aria-label="简历内容预览">
      <p className="subtle">内容预览 · 精确分页可选装 Word</p>
      {visible("photo", personal.hidden_fields, personal.field_definitions) &&
        personal.photo && <img src={personal.photo} alt="简历照片" />}
      {visible("name", personal.hidden_fields, personal.field_definitions) && (
        <h1>{personal.name}</h1>
      )}
      {(
        [
          "job_title",
          "gender",
          "age",
          "phone",
          "email",
          "gpa",
          "location",
          "website",
        ] as const
      )
        .filter((key) =>
          visible(key, personal.hidden_fields, personal.field_definitions),
        )
        .map((key) => (
          <span className="content-contact" key={key}>
            {personal[key]}
          </span>
        ))}
      {personal.custom_fields
        .filter((field) => field.visible)
        .map((field) => (
          <p key={field.id}>
            {field.label}：{field.value}
          </p>
        ))}
      {sections.map((section) => (
        <section key={section.id}>
          <h2>{section.title}</h2>
          {section.kind === "projects"
            ? items.map((item) => {
                const content = item.content;
                const visibility =
                  document.project_visibility?.[item.project_id] ?? {};
                /** 单份简历显隐覆盖仍服从已删除的默认字段定义 */
                function show(
                  key: "title" | "period" | "role" | "stack" | "description",
                ) {
                  return (
                    fieldVisible(content, visibility, key) &&
                    (!section.field_definitions ||
                      !!section.field_definitions.find(
                        (field) => field.id === key,
                      )?.visible)
                  );
                }
                return (
                  <div key={item.project_id}>
                    {show("title") && <h3>{content.title}</h3>}
                    {show("period") && <p>{content.period}</p>}
                    {projectBodyOrder(content, visibility).map((key) => {
                      if (key === "highlights")
                        return (
                          <ul key={key}>
                            {content.highlights
                              .filter((point) =>
                                item.highlight_ids.includes(point.id),
                              )
                              .map((point) => (
                                <li key={point.id}>
                                  <b>{point.title}</b> {point.text}
                                </li>
                              ))}
                          </ul>
                        );
                      if (key.startsWith("custom:")) {
                        const field = (content.custom_fields ?? []).find(
                          (value) => `custom:${value.id}` === key,
                        );
                        return field &&
                          (visibility.custom_fields?.[field.id] ??
                            field.visible) ? (
                          <p key={key}>
                            {field.label}：{field.value}
                          </p>
                        ) : null;
                      }
                      if (
                        key === "role" ||
                        key === "stack" ||
                        key === "description"
                      )
                        return show(key) ? (
                          <p key={key}>
                            {key === "stack"
                              ? content.stack.join(" · ")
                              : content[key]}
                          </p>
                        ) : null;
                      return null;
                    })}
                  </div>
                );
              })
            : section.entries
                .filter((entry) => entry.visible)
                .map((entry) => (
                  <div key={entry.id}>
                    {(["title", "subtitle", "period", "details"] as const)
                      .filter((key) =>
                        visible(
                          key,
                          entry.hidden_fields,
                          entry.field_definitions ?? section.field_definitions,
                        ),
                      )
                      .map((key) => (
                        <p key={key}>{entry[key]}</p>
                      ))}
                    {entry.custom_fields
                      .filter((field) => field.visible)
                      .map((field) => (
                        <p key={field.id}>
                          {field.label}：{field.value}
                        </p>
                      ))}
                  </div>
                ))}
        </section>
      ))}
      {Object.entries(document.extensions ?? {}).map(([owner, value]) => {
        const display =
          value && typeof value === "object" && "display" in value
            ? value.display
            : null;
        if (
          display &&
          typeof display === "object" &&
          "hidden" in display &&
          display.hidden === true
        )
          return null;
        if (
          display &&
          typeof display === "object" &&
          "title" in display &&
          "text" in display &&
          typeof display.title === "string" &&
          typeof display.text === "string"
        ) {
          return (
            <section key={owner}>
              <h2>{display.title}</h2>
              <p>{display.text}</p>
            </section>
          );
        }
        return (
          <p role="alert" key={owner}>
            扩展 {owner} 的资料已保留，需要对应插件提供导出展示。
          </p>
        );
      })}
    </article>
  );
}
