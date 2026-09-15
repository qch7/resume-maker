import { FolderOpen, ChevronDown } from "lucide-react";
import { useState } from "react";
import type { Template } from "../types";
import LibraryDialog from "./template-library/LibraryDialog";

/** 所有模板入口共用二级浏览弹窗，确认选择后才通知所在工作区。 */
export default function TemplatePicker({
  templates,
  value,
  onChange,
  disabled,
  placeholder,
  guide,
  label,
}: {
  templates: Template[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  placeholder?: string;
  guide?: string;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const name =
    placeholder ??
    (value
      ? (templates.find(
          /* 定位当前模板的显示名称。 */ (item) => item.id === value,
        )?.name ?? "请重新选择完整模板")
      : "内置 · 完整简历");
  return (
    <div className="template-library-picker">
      <span className="template-library-label">{label}</span>
      <button
        className="template-library-trigger"
        disabled={disabled}
        data-guide={guide}
        aria-label={`${label}：${name}，打开模板库`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={/* 打开独立弹窗，不改变正在编辑的模板。 */ () => setOpen(true)}
      >
        <FolderOpen size={17} />
        <span>{name}</span>
        <ChevronDown size={15} />
      </button>
      {open && (
        <LibraryDialog
          templates={templates}
          value={value}
          onClose={/* 恢复原工作区且保留原选择。 */ () => setOpen(false)}
          onChange={onChange}
        />
      )}
    </div>
  );
}
