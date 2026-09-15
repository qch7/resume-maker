import { arrayMove } from "@dnd-kit/sortable";
import { ArrowDown, ArrowUp, Pencil, X } from "lucide-react";
import {
  SortableItem,
  SortableList,
} from "../../shared/components/SortableList";
import type { Resume, Revision } from "../../shared/types";

/** 在栏目编排的项目经历栏目内管理项目顺序、固定引用与编辑入口。 */
export default function ProjectOrder({
  draft,
  revisions,
  sources,
  onChange,
  onEdit,
}: {
  draft: Resume;
  revisions: Record<string, Revision>;
  sources: Record<string, Revision>;
  onChange: (value: Resume) => void;
  onEdit: (id: string) => void;
}) {
  /** 移动项目时保留已选择的版本和亮点。 */
  function move(from: number, to: number) {
    onChange({ ...draft, items: arrayMove(draft.items, from, to) });
  }

  return (
    <div className="project-order" role="group" aria-label="项目排序与编辑">
      {!draft.items.length && (
        <p className="subtle">从“项目经历”中勾选项目，再在这里调整顺序。</p>
      )}
      <SortableList
        items={draft.items.map(
          /* 为排序手柄提供稳定标识和当前项目名称。 */ (item) => ({
            id: item.project_id,
            label:
              (sources[item.project_id] ?? revisions[item.revision_id])?.content
                .title || "项目",
          }),
        )}
        disabled={draft.items.some(
          /* 等待固定版本加载后再开放排序。 */ (item) =>
            !revisions[item.revision_id],
        )}
        onMove={move}
      >
        {draft.items.map(
          /* 只显示管理项目所需的名称、版本和操作。 */ (item, index) => {
            const revision =
              sources[item.project_id] ?? revisions[item.revision_id];
            const title = revision?.content.title || "正在读取经历版本…";
            return (
              <SortableItem
                as="article"
                className="project-order-item"
                key={item.project_id}
                id={item.project_id}
                label={`项目 ${title}`}
              >
                {
                  /* 将拖动手柄与键盘可用的移动按钮放在同一行。 */ (handle) => (
                    <>
                      <div className="project-order-info">
                        <strong>{title}</strong>
                        <span className="subtle">
                          {revision
                            ? `${revision !== revisions[item.revision_id] ? "编辑中" : "固定引用"} · r${revision.number} · `
                            : ""}
                          {item.highlight_ids.length} 条亮点
                        </span>
                      </div>
                      <div className="row">
                        <button
                          className="icon-button"
                          aria-label={`编辑项目 ${title}`}
                          onClick={
                            /* 返回项目经历编辑区。 */ () =>
                              onEdit(item.project_id)
                          }
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`上移项目 ${title}`}
                          disabled={index === 0}
                          onClick={
                            /* 将当前项目向前移动一位。 */ () =>
                              move(index, index - 1)
                          }
                        >
                          <ArrowUp size={14} />
                        </button>
                        {handle}
                        <button
                          className="icon-button"
                          aria-label={`下移项目 ${title}`}
                          disabled={index === draft.items.length - 1}
                          onClick={
                            /* 将当前项目向后移动一位。 */ () =>
                              move(index, index + 1)
                          }
                        >
                          <ArrowDown size={14} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`移除项目 ${title}`}
                          onClick={
                            /* 仅移除当前简历引用，保留原始经历。 */ () =>
                              onChange({
                                ...draft,
                                items: draft.items.filter(
                                  /* 保留其他项目引用。 */ (_, position) =>
                                    position !== index,
                                ),
                              })
                          }
                        >
                          <X size={14} />
                        </button>
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
