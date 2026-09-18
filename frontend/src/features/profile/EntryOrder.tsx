import { arrayMove } from "@dnd-kit/sortable";
import { ArrowDown, ArrowUp, Pencil, X } from "lucide-react";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import type { ResumeSection, SectionEntry } from "../../shared/types";
import { isHonorEntry } from "../honors/entry";

/** 无标题资料用已有正文标识，避免课程等条目在排序时无法区分。 */
function entryLabel(entry: SectionEntry, index: number) {
  return (
    entry.title.trim() ||
    entry.subtitle.trim() ||
    entry.details.trim().split("\n")[0] ||
    `条目 ${index + 1}`
  );
}

/** 栏目内部复用项目排序交互，直接修改个人信息与排版共用的条目顺序。 */
export default function EntryOrder({
  section,
  onChange,
  onEditHonor,
}: {
  section: ResumeSection;
  onChange: (section: ResumeSection) => void;
  onEditHonor: (sectionId: string, entry: SectionEntry) => void;
}) {
  /** 只移动同一栏目中的完整条目，来源标识、显隐和草稿内容均保留。 */
  function move(from: number, to: number) {
    onChange({ ...section, entries: arrayMove(section.entries, from, to) });
  }
  if (!section.entries.length) return null;
  return (
    <div
      className="project-order entry-order"
      role="group"
      aria-label={`${section.title}条目排序`}
    >
      <SortableList
        items={section.entries.map(
          /* 名称仅用于呈现和辅助播报，排序始终使用稳定标识。 */ (
            entry,
            index,
          ) => ({ id: entry.id, label: entryLabel(entry, index) }),
        )}
        onMove={move}
      >
        {section.entries.map(
          /* 每个文本或教育条目都具有与项目相同的上下移动和拖动手柄。 */ (
            entry,
            index,
          ) => {
            const title = entryLabel(entry, index);
            const honor = isHonorEntry(entry, section);
            return (
              <SortableItem
                as="article"
                className="project-order-item"
                key={entry.id}
                id={entry.id}
                label={`${section.title}条目 ${title}`}
              >
                {
                  /* 仅手柄启动拖动，嵌套排序不会带动外层栏目。 */ (handle) => (
                    <>
                      <div className="project-order-info">
                        <strong>{title}</strong>
                        {entry.period.trim() && (
                          <span className="subtle">{entry.period}</span>
                        )}
                        {entry.visible === false && (
                          <span className="tag warning-tag">已隐藏</span>
                        )}
                      </div>
                      <div className="row">
                        {honor && (
                          <button
                            type="button"
                            className="icon-button"
                            aria-label={`编辑荣誉 ${title}`}
                            title="编辑荣誉"
                            onClick={
                              /* 在当前编排位置打开统一荣誉编辑窗口。 */ () =>
                                onEditHonor(section.id, entry)
                            }
                          >
                            <Pencil size={14} />
                          </button>
                        )}
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`上移${section.title}条目 ${title}`}
                          disabled={index === 0}
                          onClick={
                            /* 向前移动一位，个人信息立即读取相同顺序。 */ () =>
                              move(index, index - 1)
                          }
                        >
                          <ArrowUp size={14} />
                        </button>
                        {handle}
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`下移${section.title}条目 ${title}`}
                          disabled={index === section.entries.length - 1}
                          onClick={
                            /* 向后移动一位，保持其他栏目不变。 */ () =>
                              move(index, index + 1)
                          }
                        >
                          <ArrowDown size={14} />
                        </button>
                        {honor && (
                          <button
                            type="button"
                            className="icon-button"
                            aria-label={`从简历中移除荣誉 ${title}`}
                            title="从简历中移除"
                            onClick={
                              /* 只移除当前简历条目，荣誉库及其他简历保持原样。 */ () =>
                                onChange({
                                  ...section,
                                  entries: section.entries.filter(
                                    /* 保留其他条目的资料和顺序。 */ (item) =>
                                      item.id !== entry.id,
                                  ),
                                })
                            }
                          >
                            <X size={14} />
                          </button>
                        )}
                      </div>
                    </>
                  )
                }
              </SortableItem>
            );
          },
        )}
      </SortableList>
    </div>
  );
}
