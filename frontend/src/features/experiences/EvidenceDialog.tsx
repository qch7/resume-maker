import { FolderOpen, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../shared/lib/api";
import type { Evidence, ProjectDetail } from "../../shared/types";

/** 在独立弹窗中查看引文和校验状态并定位本机来源文件 */
export default function EvidenceDialog({
  title,
  evidence,
  detail,
  onClose,
}: {
  title: string;
  evidence: Evidence[];
  detail: ProjectDetail;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [notice, setNotice] = useState("");
  const [opening, setOpening] = useState<number | null>(null);
  const snapshots = [detail.revision_snapshot, ...detail.snapshots];
  const verified = evidence.filter(
    /* 统计已经和源码或文档原文匹配的引用 */ (entry) =>
      entry.status === "code" || entry.status === "document",
  ).length;

  useEffect(
    /* 挂载时进入模态层，卸载时恢复原控件焦点 */ () => {
      const element = dialog.current;
      element?.showModal();
      return /* 清理原生模态状态及焦点约束 */ () => element?.close();
    },
    [],
  );

  /** 将快照标识和相对路径交给后端验证，错误留在当前弹窗内展示 */
  async function reveal(entry: Evidence, snapshotId: string, index: number) {
    setOpening(index);
    setNotice("");
    try {
      await api(`/projects/${detail.project.id}/sources/reveal`, "POST", {
        snapshot_id: snapshotId,
        source: entry.source,
        path: entry.path,
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法打开来源文件。");
    } finally {
      setOpening(null);
    }
  }

  return createPortal(
    <dialog
      ref={dialog}
      className="evidence-dialog"
      aria-labelledby={titleId}
      onCancel={onClose}
      onClick={
        /* 点击弹窗外的遮罩时关闭，内容留白不触发 */ (event) => {
          if (event.target !== event.currentTarget) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom
          )
            onClose();
        }
      }
    >
      <div className="dialog-title">
        <h2 id={titleId}>来源引用</h2>
        <button
          className="icon-button"
          aria-label="关闭来源引用"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      <p className="evidence-context">{title}</p>
      <p className="subtle">
        共 {evidence.length} 条引用 · {verified} 条已校验
      </p>
      {notice && (
        <p className="warning" role="alert">
          {notice}
        </p>
      )}
      {evidence.length === 0 && (
        <p className="evidence-empty subtle">这条亮点暂无来源引用。</p>
      )}
      <div className="evidence-list">
        {evidence.map(
          /* 呈现每条引文并匹配其所属快照以定位原始来源 */ (entry, index) => {
            const snapshot = snapshots.find(
              /* 已发布经历优先使用版本快照，尚未发布的 AI 建议使用最近快照 */ (
                candidate,
              ) =>
                candidate?.manifest.files.some(
                  /* 仅允许打开快照实际登记的来源文件 */ (file) =>
                    file.source === entry.source && file.path === entry.path,
                ),
            );
            return (
              <div className="evidence-entry" key={index}>
                <div className="evidence-entry-heading">
                  <span className="tag">
                    {entry.status === "unverified"
                      ? "待确认"
                      : entry.status === "user"
                        ? "本人确认"
                        : "原文匹配"}
                  </span>
                  <button
                    className="text-button"
                    title={
                      snapshot ? "在资源管理器中打开" : "没有可定位的来源文件"
                    }
                    aria-label={`在资源管理器中打开 ${entry.path || "来源文件"}`}
                    disabled={!snapshot || opening !== null}
                    onClick={
                      /* 请求在文件管理器中选中当前引用文件 */ () => {
                        if (snapshot) void reveal(entry, snapshot.id, index);
                      }
                    }
                  >
                    <FolderOpen size={15} />
                    {opening === index ? "正在打开…" : "在资源管理器中打开"}
                  </button>
                </div>
                <code>
                  {entry.source}/{entry.path}:{entry.line_start}–
                  {entry.line_end}
                </code>
                <pre>{entry.quote}</pre>
              </div>
            );
          },
        )}
      </div>
    </dialog>,
    document.body,
  );
}
