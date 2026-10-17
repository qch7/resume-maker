import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ResumeDocument } from "@resume-maker/plugin-sdk/shared/types/index";
import type { LayoutItem } from "@resume-maker/plugin-sdk/shared/resume/itemLayout";
import { groupLayoutItems } from "./layoutItemGroups";

/** 按栏目浏览或搜索文字，不把整份简历塞进原生下拉框 */
export default function LayoutItemPicker({
  document,
  items,
  selectedKey,
  onSelect,
}: {
  document: ResumeDocument;
  items: LayoutItem[];
  selectedKey: string;
  onSelect: (key: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [opened, setOpened] = useState<string[]>([]);
  const allGroups = groupLayoutItems(document, items);
  const selectedGroup = allGroups.find((group) =>
    group.items.some((item) => item.key === selectedKey),
  )?.id;
  const groups = groupLayoutItems(document, items, query);
  useEffect(() => {
    setQuery("");
    if (selectedGroup)
      setOpened((current) =>
        current.includes(selectedGroup) ? current : [...current, selectedGroup],
      );
  }, [selectedGroup, selectedKey]);
  return (
    <div className="layout-item-picker">
      <div className="layout-item-search">
        <Search size={15} aria-hidden="true" />
        <input
          type="search"
          aria-label="搜索要调整的文字"
          placeholder="搜索栏目、内容或字段…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {query && (
          <button
            type="button"
            className="icon-button"
            aria-label="清空文字搜索"
            onClick={() => setQuery("")}
          >
            <X size={14} />
          </button>
        )}
      </div>
      <div className="layout-item-list" aria-label="按栏目选择文字">
        {!groups.length && (
          <p className="subtle">
            {items.length
              ? "没有匹配的文字，换个关键词试试。"
              : "暂无可见文字。"}
          </p>
        )}
        {groups.map((group) => (
          <details
            key={group.id}
            open={!!query.trim() || opened.includes(group.id)}
            onToggle={(event) => {
              if (query.trim()) return;
              const open = event.currentTarget.open;
              setOpened((current) =>
                open
                  ? current.includes(group.id)
                    ? current
                    : [...current, group.id]
                  : current.filter((id) => id !== group.id),
              );
            }}
          >
            <summary>
              <span>{group.title}</span>
              <small>{group.items.length} 项</small>
            </summary>
            {group.items.map((item) => (
              <button
                key={item.key}
                type="button"
                className="layout-item-choice"
                aria-pressed={item.key === selectedKey}
                title={item.label}
                onClick={() => {
                  onSelect(item.key);
                  setQuery("");
                }}
              >
                {item.label.startsWith(`${group.title} / `)
                  ? item.label.slice(group.title.length + 3)
                  : item.label}
              </button>
            ))}
          </details>
        ))}
      </div>
    </div>
  );
}
