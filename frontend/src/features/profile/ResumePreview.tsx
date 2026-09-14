import type { ReactNode } from "react";
import type { Resume, ResumeSection } from "../../shared/types";
import {
  displayedPersonal,
  filledEntries,
  hasSectionContent,
  siblings,
} from "./document";

/** 展示与完整 Word 导出一致的顶部资料和栏目层级，保留项目区的交互操作。 */
export default function ResumePreview({
  draft,
  projects,
}: {
  draft: Resume;
  projects: ReactNode;
}) {
  const content = !draft.template_id ? draft.document : null;
  if (!content)
    return (
      <div className="resume-paper">
        <div className="paper-heading">项目经历</div>
        {projects}
      </div>
    );
  const { sections } = content;
  const personal = displayedPersonal(content.personal);
  const age = /^\d+$/.test(personal.age) ? `${personal.age} 岁` : personal.age;
  const contacts = [
    ["gpa", "专业成绩", personal.gpa],
    ["phone", "电话", personal.phone],
    ["email", "邮箱", personal.email],
    ["location", "所在地", personal.location],
    ["website", "个人主页", personal.website],
    ...personal.custom_fields.map(
      /* 自定义信息沿用联系方式的双列排版。 */ (field) => [
        `custom-${field.id}`,
        field.label,
        field.value,
      ],
    ),
  ];
  const visible = siblings(sections).filter(
    /* 只排版含可见资料的大栏目。 */ (section) =>
      hasSectionContent(section, sections, draft.items.length),
  );
  return (
    <div className="resume-paper full-resume-paper">
      <div className={`resume-banner ${personal.photo ? "with-photo" : ""}`}>
        {personal.photo && <img src={personal.photo} alt="简历照片" />}
        <div className="resume-identity">
          <div>
            {!personal.hidden_fields.includes("name") && (
              <strong>{personal.name || "你的姓名"}</strong>
            )}
            {(personal.gender || age) && (
              <span>{[personal.gender, age].filter(Boolean).join(" ")}</span>
            )}
          </div>
          {personal.job_title && <p>{personal.job_title}</p>}
        </div>
        <div className="resume-banner-title">
          <strong>个人简历</strong>
          <span>PERSONAL RESUME</span>
        </div>
      </div>
      <div className="resume-full-body">
        <div className="resume-contacts">
          {contacts
            .filter(/* 空联系方式不占据排版位置。 */ (item) => item[2])
            .map(
              /* 基本信息以两列展示，重名标签使用独立标识。 */ ([
                id,
                label,
                text,
              ]) => (
                <span key={id}>
                  {label}：{text}
                </span>
              ),
            )}
        </div>
        {!visible.length && (
          <div className="empty compact preview-empty">
            <p>从你的信息开始</p>
            <span>填写个人资料、添加教育经历，或从项目工作台选入项目。</span>
          </div>
        )}
        {visible.map(
          /* 大栏目按照编排顺序，与项目经历平级。 */ (section) => (
            <section
              key={section.id}
              className="resume-major-section"
              data-section-id={section.id}
            >
              <h2 className="resume-section-heading">
                <span>{section.title}</span>
              </h2>
              {section.kind === "projects" ? (
                draft.items.length > 0 ? (
                  projects
                ) : null
              ) : (
                <EntryPreview section={section} />
              )}
              {siblings(sections, section.id)
                .filter(
                  /* 隐藏和空子栏目不显示标题，项目区也支持附加子栏目。 */ (
                    child,
                  ) => child.visible && filledEntries(child).length > 0,
                )
                .map(
                  /* 子栏目排在父级资料或项目经历之后。 */ (child) => (
                    <div
                      className="resume-minor-section"
                      key={child.id}
                      data-section-id={child.id}
                    >
                      <h3>{child.title}</h3>
                      <EntryPreview section={child} />
                    </div>
                  ),
                )}
            </section>
          ),
        )}
      </div>
    </div>
  );
}

/** 教育经历使用日期、学校、专业三列，其他资料使用标题与正文结构。 */
function EntryPreview({ section }: { section: ResumeSection }) {
  return (
    <>
      {filledEntries(section).map(
        /* 按用户定义的条目顺序呈现正文。 */ (entry) => (
          <article className="resume-info-entry" key={entry.id}>
            {(entry.title || entry.subtitle || entry.period) && (
              <div
                className={`resume-info-title ${section.kind === "education" ? "education-title" : ""}`}
              >
                {section.kind === "education" ? (
                  <>
                    <b>{entry.period}</b>
                    <b>{entry.title}</b>
                    <b>{entry.subtitle}</b>
                  </>
                ) : (
                  <>
                    <b>{entry.title}</b>
                    <span>{entry.subtitle}</span>
                    <span>{entry.period}</span>
                  </>
                )}
              </div>
            )}
            {entry.details && <p>{entry.details}</p>}
            {entry.custom_fields.map(
              /* 条目内的自定义信息紧跟正文显示。 */ (field) => (
                <p key={field.id}>
                  <b>{field.label}：</b>
                  {field.value}
                </p>
              ),
            )}
          </article>
        ),
      )}
    </>
  );
}
