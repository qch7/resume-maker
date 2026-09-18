import { Check, FileText, Heart } from "lucide-react";
import Thumbnail from "./Thumbnail";
import { templateDate, type LibraryTemplate } from "./library";

/** 列表和卡片统一使用独立选择与 Like 按钮，键盘也可完成全部操作。 */
export default function TemplateEntries({
  items,
  view,
  selected,
  current,
  categoryName,
  pending,
  onSelect,
  onConfirm,
  onLike,
}: {
  items: LibraryTemplate[];
  view: "cards" | "list";
  selected: string;
  current: string;
  categoryName: (id: string) => string;
  pending: boolean;
  onSelect: (id: string) => void;
  onConfirm: (id: string) => void;
  onLike: (item: LibraryTemplate) => void;
}) {
  return (
    <div className={`library-entries library-${view}`}>
      {view === "list" && (
        <div className="library-list-heading" aria-hidden="true">
          <span>名称</span>
          <span>分类</span>
          <span>保存日期</span>
          <span>Like</span>
        </div>
      )}
      {items.map(
        /* 每个模板均可选择、双击确认或单独收藏。 */ (item) => (
          <div
            key={item.id}
            className={`library-entry ${selected === item.id ? "is-selected" : ""}`}
          >
            {view === "cards" && (
              <div className="library-card-preview">
                <Thumbnail id={item.id} name={item.name} />
                <button
                  className="library-preview-select"
                  aria-label={`选择 ${item.name}`}
                  aria-pressed={selected === item.id}
                  onClick={/* 单击只改变弹窗内选择。 */ () => onSelect(item.id)}
                  onDoubleClick={
                    /* 双击直接确认模板。 */ () => onConfirm(item.id)
                  }
                />
                {current === item.id && (
                  <span className="library-current">
                    <Check size={12} />
                    当前模板
                  </span>
                )}
              </div>
            )}
            <button
              className="library-entry-name"
              title={item.name}
              aria-pressed={selected === item.id}
              onClick={/* 列表名称支持键盘选择。 */ () => onSelect(item.id)}
              onDoubleClick={
                /* 与资源管理器的双击打开行为保持一致。 */ () =>
                  onConfirm(item.id)
              }
            >
              <FileText size={17} />
              <span>{item.name}</span>
              {view === "list" && current === item.id && (
                <Check size={14} aria-label="当前模板" />
              )}
            </button>
            <span className="library-entry-category">
              {categoryName(item.category_id)}
            </span>
            <span className="library-entry-date">
              {templateDate(item.created_at)}
            </span>
            <button
              className={`library-like ${item.liked ? "is-liked" : ""}`}
              aria-label={`${item.liked ? "取消喜欢" : "喜欢"} ${item.name}`}
              title={item.liked ? "取消 Like" : "Like · 喜欢"}
              aria-pressed={item.liked}
              disabled={pending || !!item.deleted_at}
              onClick={
                /* 收藏不改变当前选择，也不关闭弹窗。 */ () => onLike(item)
              }
            >
              <Heart size={17} fill={item.liked ? "currentColor" : "none"} />
            </button>
          </div>
        ),
      )}
    </div>
  );
}
