import { useId, useState } from "react";
import {
  ExternalLink,
  MessageSquareText,
  Pencil,
  Star,
  Trash2,
} from "lucide-react";
import { bookmarkDescription, type Bookmark } from "./model";

/** 共用卡片和列表内容，合并重复说明并按需展开备注 */
export default function BookmarkCard({
  item,
  group,
  busy,
  onTag,
  onFavorite,
  onEdit,
  onDelete,
}: {
  item: Bookmark;
  group: string;
  busy: boolean;
  onTag: (tag: string) => void;
  onFavorite: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [notesOpen, setNotesOpen] = useState(false);
  const notesId = useId();
  const description = bookmarkDescription(item);
  return (
    <article className="recruitment-card">
      <div className="recruitment-info">
        <header>
          <span className="recruitment-monogram">{item.name.slice(0, 1)}</span>
          <div className="grow">
            <h2>{item.name}</h2>
            {group && <small>{group}</small>}
          </div>
        </header>
        {(description || item.tags.length > 0) && (
          <div className="recruitment-summary">
            {description && (
              <p className="recruitment-description">{description}</p>
            )}
            {!!item.tags.length && (
              <div className="recruitment-tags">
                {item.tags.map((tag, index) => (
                  <button
                    key={index}
                    className="tag"
                    onClick={() => onTag(tag)}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="recruitment-links">
        {item.links.map((link, index) => (
          <a
            key={index}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            title={link.url}
          >
            {link.label}
            <ExternalLink size={12} />
          </a>
        ))}
      </div>
      <footer>
        {item.notes && (
          <button
            className="icon-button recruitment-notes-toggle"
            aria-label={`${notesOpen ? "收起" : "查看"}${item.name}的备注和来源`}
            title={notesOpen ? "收起备注" : "备注和来源"}
            aria-expanded={notesOpen}
            aria-controls={notesId}
            onClick={() => setNotesOpen(!notesOpen)}
          >
            <MessageSquareText size={15} />
            <span>备注</span>
          </button>
        )}
        <button
          className={`icon-button ${item.favorite ? "is-favorite" : ""}`}
          aria-label={`${item.favorite ? "取消星标" : "星标"}${item.name}`}
          title={item.favorite ? "取消星标" : "星标"}
          aria-pressed={item.favorite}
          disabled={busy}
          onClick={onFavorite}
        >
          <Star size={16} fill={item.favorite ? "currentColor" : "none"} />
        </button>
        <button
          className="icon-button"
          aria-label={`编辑${item.name}`}
          title="编辑"
          disabled={busy}
          onClick={onEdit}
        >
          <Pencil size={15} />
        </button>
        <button
          className="icon-button"
          aria-label={`删除${item.name}`}
          title="删除"
          disabled={busy}
          onClick={onDelete}
        >
          <Trash2 size={15} />
        </button>
      </footer>
      {item.notes && (
        <p id={notesId} className="recruitment-notes" hidden={!notesOpen}>
          {item.notes}
        </p>
      )}
    </article>
  );
}
