import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { storage } from "../lib/storage";

import type { DocumentImporter } from "../types/imports";

/** 从当前宿主读取导入能力，隐藏页面停止订阅并拒绝迟到响应 */
export function useDocumentImporters(
  purpose: "template" | "certificate",
  active: boolean,
) {
  const [items, setItems] = useState<DocumentImporter[]>([]);
  const selectionKey = `rm.document.importer.${purpose}`;
  const [selected, setSelection] = useState(
    () => storage.getItem(selectionKey) ?? "",
  );
  const [conflict, setConflict] = useState("");
  /** 只接受用户的明确选择，存量处理器缺失时保留原值 */
  function setSelected(identifier: string) {
    setSelection(identifier);
    setConflict("");
  }
  /** 实际内容探测出现多项匹配时展开选择，普通失败仍由原表单报告 */
  function reportError(reason: unknown) {
    if (
      reason instanceof ApiError &&
      reason.status === 409 &&
      reason.message.includes("多个导入器")
    )
      setConflict("多个处理器可以处理此文件，请明确选择后重试。");
  }
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    storage.setItem(selectionKey, selected);
  }, [selectionKey, selected]);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setLoading(true);
    void api<DocumentImporter[]>(
      `/document-importers?purpose=${purpose}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (controller.signal.aborted) return;
        setItems(value);
        setError("");
      })
      .catch((reason: Error) => {
        if (!controller.signal.aborted) setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [purpose, active]);
  const missing = !!selected && !items.some((item) => item.id === selected);
  const available = !loading && !error && !!items.length && !missing;
  const extensions = [
    ...new Set(
      items
        .filter((item) => !selected || item.id === selected)
        .flatMap((item) => item.extensions),
    ),
  ];
  return {
    items,
    selected,
    setSelected,
    conflict,
    reportError,
    error,
    loading,
    available,
    missing,
    extensions,
    limits: items.find((item) => !selected || item.id === selected)?.limits,
  };
}
