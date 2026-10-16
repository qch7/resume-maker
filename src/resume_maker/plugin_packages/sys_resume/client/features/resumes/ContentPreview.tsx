import type {
  DefaultField,
  Experience,
  ResumeDocument,
  ResumeItem,
} from "@resume-maker/plugin-sdk/shared/types/index";
import { fieldVisible } from "@resume-maker/plugin-sdk/shared/resume/visibility";
import { projectBodyOrder } from "@resume-maker/plugin-sdk/shared/resume/bodyOrder";
import { pageLayout } from "@resume-maker/plugin-sdk/shared/resume/pageLayout";
import {
  itemCss,
  itemKey,
  itemType,
  paragraphCss,
} from "@resume-maker/plugin-sdk/shared/resume/itemLayout";

/** 内容预览遵守显隐、固定引用，不依赖 Word 或远端模型 */
export default function ContentPreview({ input }: { input: string | null }) {
  if (!input) return <p className="subtle">正在读取经历版本…</p>;
  const { document, items } = JSON.parse(input) as {
    document: ResumeDocument;
    items: (ResumeItem & { content: Experience })[];
  };
  const personal = document.personal;
  const layout = pageLayout(document);
  /** 预览使用与 Word 相同的语义键及样式覆盖顺序 */
  function style(type: string, ...parts: string[]) {
    return itemCss(layout, itemKey(...parts), type);
  }
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
  const contacts = (
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
    .filter(
      (field) =>
        personal[field].trim() &&
        visible(field, personal.hidden_fields, personal.field_definitions),
    )
    .map((field) => ({
      field,
      key: itemKey("personal", field),
      type: itemType("personal", field),
    }));
  return (
    <article className="content-preview" aria-label="简历内容预览">
      <p className="subtle">内容预览 · 精确分页可选装 Word</p>
      {visible("photo", personal.hidden_fields, personal.field_definitions) &&
        personal.photo && <img src={personal.photo} alt="简历照片" />}
      {visible("name", personal.hidden_fields, personal.field_definitions) && (
        <h1 style={style("name", "personal", "name")}>{personal.name}</h1>
      )}
      {contacts.length > 0 && (
        <div style={paragraphCss(layout, contacts)}>
          {contacts.map(({ field, key, type }) => (
            <span
              className="content-contact"
              key={key}
              style={{ fontSize: itemCss(layout, key, type).fontSize }}
            >
              {personal[field]}
            </span>
          ))}
        </div>
      )}
      {personal.custom_fields
        .filter(
          (field) => field.visible && field.label.trim() && field.value.trim(),
        )
        .map((field) => (
          <p
            key={field.id}
            style={style("custom", "personal", "custom", field.id)}
          >
            {field.label}：{field.value}
          </p>
        ))}
      {sections.map((section) => (
        <section key={section.id}>
          <h2 style={style("section_title", "section", section.id, "title")}>
            {section.title}
          </h2>
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
                    {show("title") && (
                      <h3
                        style={style(
                          "title",
                          "project",
                          item.project_id,
                          "title",
                        )}
                      >
                        {content.title}
                      </h3>
                    )}
                    {show("period") && (
                      <p
                        style={style(
                          "period",
                          "project",
                          item.project_id,
                          "period",
                        )}
                      >
                        {content.period}
                      </p>
                    )}
                    {projectBodyOrder(content, visibility).map((key) => {
                      if (key === "highlights")
                        return (
                          <ul key={key}>
                            {content.highlights
                              .filter((point) =>
                                item.highlight_ids.includes(point.id),
                              )
                              .map((point) => (
                                <li
                                  key={point.id}
                                  style={style(
                                    "highlight",
                                    "project",
                                    item.project_id,
                                    "highlight",
                                    point.id,
                                  )}
                                >
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
                          field.label.trim() &&
                          field.value.trim() &&
                          (visibility.custom_fields?.[field.id] ??
                            field.visible) ? (
                          <p
                            key={key}
                            style={style(
                              "custom",
                              "project",
                              item.project_id,
                              "custom",
                              field.id,
                            )}
                          >
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
                          <p
                            key={key}
                            style={style(
                              itemType("project", key),
                              "project",
                              item.project_id,
                              key,
                            )}
                          >
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
                        <p
                          key={key}
                          style={style(
                            itemType("entry", key),
                            "entry",
                            section.id,
                            entry.id,
                            key,
                          )}
                        >
                          {entry[key]}
                        </p>
                      ))}
                    {entry.custom_fields
                      .filter(
                        (field) =>
                          field.visible &&
                          field.label.trim() &&
                          field.value.trim(),
                      )
                      .map((field) => (
                        <p
                          key={field.id}
                          style={style(
                            "custom",
                            "entry",
                            section.id,
                            entry.id,
                            "custom",
                            field.id,
                          )}
                        >
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
