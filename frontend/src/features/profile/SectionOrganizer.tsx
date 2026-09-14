import {
  ArrowDown,
  ArrowUp,
  Eye,
  EyeOff,
  LockKeyhole,
  Plus,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import type { ResumeDocument, ResumeSection } from "../../shared/types";
import { moveSection, removeSection, siblings } from "./document";

/** 提供大栏目与子栏目的层级选择、显隐、增删和同级排序。 */
export default function SectionOrganizer({
  value,
  onChange,
  onInfo,
}: {
  value: ResumeDocument;
  onChange: (value: ResumeDocument) => void;
  onInfo: () => void;
}) {
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<"education" | "text">("text");
  const [deleted, setDeleted] = useState<ResumeSection | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  useEffect(
    /* 新子栏目出现后选中名称，方便直接输入而不打断其他栏目编辑。 */ () => {
      if (!focusId) return;
      const input = document.getElementById(
        `section-title-${focusId}`,
      ) as HTMLInputElement | null;
      input?.focus();
      input?.select();
      setFocusId(null);
    },
    [focusId],
  );
  /** 更新栏目结构时保留顶部个人信息。 */
  function change(sections: ResumeSection[]) {
    onChange({ ...value, sections });
  }
  /** 替换一个栏目，不重置其资料。 */
  function update(section: ResumeSection) {
    change(
      value.sections.map(
        /* 根据标识替换栏目。 */ (item) =>
          item.id === section.id ? section : item,
      ),
    );
  }
  /** 创建指定类型的大栏目并清空输入。 */
  function add() {
    if (!title.trim() || value.sections.length >= 40) return;
    change([
      ...value.sections,
      {
        id: crypto.randomUUID(),
        title: title.trim(),
        kind,
        parent_id: null,
        visible: true,
        entries: [],
      },
    ]);
    setTitle("");
  }
  /** 在当前大栏目末尾直接添加子栏目，维持两级结构及总数限制。 */
  function addChild(parent: ResumeSection) {
    if (parent.parent_id || value.sections.length >= 40) return;
    const id = crypto.randomUUID();
    change([
      ...value.sections,
      {
        id,
        title: "新子栏目",
        kind: "text",
        parent_id: parent.id,
        visible: true,
        entries: [],
      },
    ]);
    setFocusId(id);
  }
  /** 同级排序独立于项目区内部的经历排序。 */
  function renderGroup(parent: string | null = null) {
    const group = siblings(value.sections, parent);
    if (!group.length) return null;
    return (
      <SortableList
        items={group.map(
          /* 为辅助播报提供栏目标题。 */ (section) => ({
            id: section.id,
            label: section.title,
          }),
        )}
        onMove={
          /* 拖动只移动本层级。 */ (from, to) =>
            change(moveSection(value.sections, parent, from, to))
        }
      >
        {group.map(
          /* 大栏目携带子栏目一起呈现和移动。 */ (section, index) => (
            <SortableItem
              id={section.id}
              key={section.id}
              label={`栏目 ${section.title}`}
              className={`organizer-card ${parent ? "organizer-child" : ""}`}
            >
              {
                /* 在标题行放置排序手柄，表单编辑不会触发拖动。 */ (handle) => (
                  <>
                    <div className="organizer-row">
                      {handle}
                      <span className="section-number">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <input
                        id={`section-title-${section.id}`}
                        aria-label={`栏目名称 ${section.title}`}
                        value={section.title}
                        maxLength={100}
                        onChange={
                          /* 标题不能为空，输入时保留空格供继续编辑。 */ (
                            event,
                          ) =>
                            update({
                              ...section,
                              title: event.target.value || " ",
                            })
                        }
                      />
                      <div className="row">
                        {!parent && (
                          <button
                            className="text-button"
                            aria-label={`为${section.title}添加子栏目`}
                            disabled={value.sections.length >= 40}
                            onClick={
                              /* 新栏目直接归入当前大栏目。 */ () =>
                                addChild(section)
                            }
                          >
                            <Plus size={14} />
                            添加子栏目
                          </button>
                        )}
                        <button
                          className="icon-button"
                          aria-label={`上移栏目 ${section.title}`}
                          disabled={index === 0}
                          onClick={
                            /* 上移当前栏目。 */ () =>
                              change(
                                moveSection(
                                  value.sections,
                                  parent,
                                  index,
                                  index - 1,
                                ),
                              )
                          }
                        >
                          <ArrowUp size={14} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`下移栏目 ${section.title}`}
                          disabled={index === group.length - 1}
                          onClick={
                            /* 下移当前栏目。 */ () =>
                              change(
                                moveSection(
                                  value.sections,
                                  parent,
                                  index,
                                  index + 1,
                                ),
                              )
                          }
                        >
                          <ArrowDown size={14} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`${section.visible ? "隐藏" : "显示"}栏目 ${section.title}`}
                          aria-pressed={section.visible}
                          onClick={
                            /* 保留资料，仅控制排版显隐。 */ () =>
                              update({ ...section, visible: !section.visible })
                          }
                        >
                          {section.visible ? (
                            <Eye size={15} />
                          ) : (
                            <EyeOff size={15} />
                          )}
                        </button>
                        <button
                          className="icon-button danger-hover"
                          aria-label={`删除栏目 ${section.title}`}
                          disabled={section.kind === "projects"}
                          title={
                            section.kind === "projects"
                              ? "项目经历可隐藏，保留版本引用"
                              : "删除栏目；子栏目会保留为大栏目"
                          }
                          onClick={
                            /* 保存删除项以供撤销，子栏目提升到顶层。 */ () => {
                              setDeleted(section);
                              change(removeSection(value.sections, section.id));
                            }
                          }
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                    <div className="organizer-meta">
                      <span
                        className={`tag ${section.visible ? "" : "warning-tag"}`}
                      >
                        {section.visible
                          ? parent
                            ? "子栏目"
                            : "大栏目"
                          : "已隐藏"}
                      </span>
                      <label>
                        所属层级
                        <select
                          aria-label={`${section.title}所属层级`}
                          value={section.parent_id ?? ""}
                          disabled={
                            section.kind === "projects" ||
                            siblings(value.sections, section.id).length > 0
                          }
                          onChange={
                            /* 改变父级只调整排版层级，资料保持不变。 */ (
                              event,
                            ) =>
                              update({
                                ...section,
                                parent_id: event.target.value || null,
                              })
                          }
                        >
                          <option value="">独立大栏目</option>
                          {siblings(value.sections)
                            .filter(
                              /* 排除自身，子栏目只归入顶层栏目以避免循环。 */ (
                                item,
                              ) => item.id !== section.id,
                            )
                            .map(
                              /* 选择其他大栏目作为父级。 */ (item) => (
                                <option key={item.id} value={item.id}>
                                  {item.title} / 子栏目
                                </option>
                              ),
                            )}
                        </select>
                      </label>
                      <span className="subtle">
                        {section.kind === "projects"
                          ? "引用项目工作台"
                          : `${section.entries.length} 条资料`}
                      </span>
                    </div>
                    {!parent && renderGroup(section.id)}
                  </>
                )
              }
            </SortableItem>
          ),
        )}
      </SortableList>
    );
  }
  return (
    <>
      <header className="workspace-header profile-heading">
        <div>
          <h1>栏目编排</h1>
        </div>
        <button onClick={onInfo}>填写资料</button>
      </header>
      <div className="workspace-scroll profile-scroll">
        <div className="organizer-pinned">
          <LockKeyhole size={18} />
          <strong>基本信息</strong>
          <button className="text-button" onClick={onInfo}>
            编辑
          </button>
        </div>
        {renderGroup()}
        {deleted && (
          <div className="organizer-undo" role="status">
            已删除“{deleted.title}”，子栏目已保留。
            <button
              className="text-button"
              disabled={value.sections.length >= 40}
              onClick={
                /* 恢复被删除栏目正文，不覆盖删除后的其他编排。 */ () => {
                  change([...value.sections, { ...deleted, parent_id: null }]);
                  setDeleted(null);
                }
              }
            >
              撤销删除
            </button>
          </div>
        )}
        <form
          className="profile-card add-section"
          onSubmit={
            /* 添加自定义大栏目并阻止页面提交。 */ (event) => {
              event.preventDefault();
              add();
            }
          }
        >
          <h2>添加大栏目</h2>
          <div className="profile-fields">
            <label>
              栏目名称
              <input
                aria-label="新栏目名称"
                value={title}
                maxLength={100}
                placeholder="如：实习经历、校园活动、个人评价"
                onChange={
                  /* 记录待创建栏目名称。 */ (event) =>
                    setTitle(event.target.value)
                }
              />
            </label>
            <label>
              内容排版
              <select
                value={kind}
                onChange={
                  /* 选择通用资料或教育经历布局。 */ (event) =>
                    setKind(event.target.value as "education" | "text")
                }
              >
                <option value="text">通用 · 标题与正文</option>
                <option value="education">教育 · 时间 / 学校 / 专业</option>
              </select>
            </label>
          </div>
          <button
            className="primary"
            type="submit"
            disabled={!title.trim() || value.sections.length >= 40}
          >
            <Plus size={15} />
            添加栏目
          </button>
        </form>
      </div>
    </>
  );
}
