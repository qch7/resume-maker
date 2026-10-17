import LayoutText from "./LayoutText";
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
  layoutItems,
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
  const selectableKeys = new Set(
    layoutItems(document, items).map((item) => item.key),
  );
  /** 预览使用 Word 的同一语义键及样式覆盖顺序，选择不参与样式寻址 */
  function textProps(type: string, ...parts: string[]) {
    const key = itemKey(...parts);
    return {
      layoutKey: selectableKeys.has(key) ? key : undefined,
      style: itemCss(layout, key, type),
    };
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
        <LayoutText as="h1" {...textProps("name", "personal", "name")}>
          {personal.name}
        </LayoutText>
      )}
      {contacts.length > 0 && (
        <div style={paragraphCss(layout, contacts)}>
          {contacts.map(({ field, key, type }) => (
            <LayoutText
              as="span"
              layoutKey={key}
              className="content-contact"
              key={key}
              style={{ fontSize: itemCss(layout, key, type).fontSize }}
            >
              {personal[field]}
            </LayoutText>
          ))}
        </div>
      )}
      {personal.custom_fields
        .filter(
          (field) => field.visible && field.label.trim() && field.value.trim(),
        )
        .map((field) => (
          <LayoutText
            as="p"
            key={field.id}
            {...textProps("custom", "personal", "custom", field.id)}
          >
            {field.label}：{field.value}
          </LayoutText>
        ))}
      {sections.map((section) => (
        <section key={section.id}>
          <LayoutText
            as="h2"
            {...textProps("section_title", "section", section.id, "title")}
          >
            {section.title}
          </LayoutText>
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
                      <LayoutText
                        as="h3"
                        {...textProps(
                          "title",
                          "project",
                          item.project_id,
                          "title",
                        )}
                      >
                        {content.title}
                      </LayoutText>
                    )}
                    {show("period") && (
                      <LayoutText
                        as="p"
                        {...textProps(
                          "period",
                          "project",
                          item.project_id,
                          "period",
                        )}
                      >
                        {content.period}
                      </LayoutText>
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
                                <LayoutText
                                  as="li"
                                  key={point.id}
                                  {...textProps(
                                    "highlight",
                                    "project",
                                    item.project_id,
                                    "highlight",
                                    point.id,
                                  )}
                                >
                                  <b>{point.title}</b> {point.text}
                                </LayoutText>
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
                          <LayoutText
                            as="p"
                            key={key}
                            {...textProps(
                              "custom",
                              "project",
                              item.project_id,
                              "custom",
                              field.id,
                            )}
                          >
                            {field.label}：{field.value}
                          </LayoutText>
                        ) : null;
                      }
                      if (
                        key === "role" ||
                        key === "stack" ||
                        key === "description"
                      )
                        return show(key) ? (
                          <LayoutText
                            as="p"
                            key={key}
                            {...textProps(
                              itemType("project", key),
                              "project",
                              item.project_id,
                              key,
                            )}
                          >
                            {key === "stack"
                              ? content.stack.join(" · ")
                              : content[key]}
                          </LayoutText>
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
                        <LayoutText
                          as="p"
                          key={key}
                          {...textProps(
                            itemType("entry", key),
                            "entry",
                            section.id,
                            entry.id,
                            key,
                          )}
                        >
                          {entry[key]}
                        </LayoutText>
                      ))}
                    {entry.custom_fields
                      .filter(
                        (field) =>
                          field.visible &&
                          field.label.trim() &&
                          field.value.trim(),
                      )
                      .map((field) => (
                        <LayoutText
                          as="p"
                          key={field.id}
                          {...textProps(
                            "custom",
                            "entry",
                            section.id,
                            entry.id,
                            "custom",
                            field.id,
                          )}
                        >
                          {field.label}：{field.value}
                        </LayoutText>
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
