import { useRef, type ReactNode } from "react";
import {
  closestCenter,
  DndContext,
  getScrollableAncestors,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type CollisionDetection,
  type Modifier,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Menu } from "lucide-react";

const verticalOnly: Modifier = ({ transform }) => ({ ...transform, x: 0 });

export function SortableList({
  items,
  disabled = false,
  onMove,
  children,
}: {
  items: { id: string; label: string }[];
  disabled?: boolean;
  onMove: (from: number, to: number) => void;
  children: ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
  const collisionDetection: CollisionDetection = (args) => {
    // 松手落在列表或滚动视口外时取消；键盘排序继续按条目位置定位。
    if (args.pointerCoordinates && root.current) {
      const { x, y } = args.pointerCoordinates;
      const bounds = [root.current, ...getScrollableAncestors(root.current)];
      if (
        bounds.some((node) => {
          const r = node.getBoundingClientRect();
          return x < r.left || x > r.right || y < r.top || y > r.bottom;
        })
      )
        return [];
      // 亮点高度不同，按手柄所在位置确定落点，避免大卡片中心偏移。
      return closestCenter({
        ...args,
        collisionRect: {
          left: x,
          right: x,
          top: y,
          bottom: y,
          width: 0,
          height: 0,
        },
      });
    }
    return closestCenter(args);
  };
  const position = (id: string | number) =>
    items.findIndex((item) => item.id === id);
  const label = (id: string | number) => items[position(id)]?.label ?? "条目";
  return (
    <DndContext
      sensors={sensors}
      modifiers={[verticalOnly]}
      collisionDetection={collisionDetection}
      onDragEnd={({ active, over }) => {
        const from = position(active.id);
        const to = over ? position(over.id) : -1;
        if (!disabled && from >= 0 && to >= 0 && from !== to) onMove(from, to);
      }}
      accessibility={{
        screenReaderInstructions: {
          draggable: "按空格开始排序，上下方向键移动，再按空格放下，Esc 取消。",
        },
        announcements: {
          onDragStart: ({ active }) => `正在拖动${label(active.id)}。`,
          onDragOver: ({ over }) =>
            over
              ? `放到第 ${position(over.id) + 1} 位。`
              : "移出列表，松手取消。",
          onDragEnd: ({ active, over }) =>
            over
              ? `${label(active.id)}已放到第 ${position(over.id) + 1} 位。`
              : "已取消排序。",
          onDragCancel: () => "已取消排序。",
        },
      }}
    >
      <SortableContext
        items={items}
        strategy={verticalListSortingStrategy}
        disabled={disabled || items.length < 2}
      >
        <div ref={root} className="sortable-list">
          {children}
        </div>
      </SortableContext>
    </DndContext>
  );
}

export function SortableItem({
  id,
  label,
  className,
  as: Tag = "div",
  children,
}: {
  id: string;
  label: string;
  className: string;
  as?: "div" | "article";
  children: (handle: ReactNode) => ReactNode;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
    activeIndex,
    index,
    overIndex,
  } = useSortable({ id });
  return (
    <Tag
      ref={setNodeRef}
      className={`${className} sortable-item${isDragging ? " sort-dragging" : ""}`}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      data-sort-id={id}
      data-drop={
        index === overIndex && index !== activeIndex
          ? activeIndex < index
            ? "after"
            : "before"
          : undefined
      }
    >
      {children(
        <button
          type="button"
          className="icon-button sort-handle"
          ref={setActivatorNodeRef}
          {...attributes}
          {...listeners}
          disabled={attributes["aria-disabled"] === true}
          aria-label={`拖动排序 ${label}`}
          aria-roledescription="排序手柄"
          title="按住拖动排序；也可按空格后用上下方向键移动，Esc 取消"
        >
          <Menu size={14} />
        </button>,
      )}
    </Tag>
  );
}
