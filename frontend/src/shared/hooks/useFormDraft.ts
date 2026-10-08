import { useEffect, useRef, useState } from "react";
import {
  acceptDraftConfirmation,
  equal,
  mergeDraft,
  restoreDraft,
  type DraftEnvelope,
} from "../lib/mergeDraft";
import { recoveryCopies } from "../lib/recoveryCopies";
import { loadLocal, storage } from "../lib/storage";

/** 管理表单读取基线、冲突恢复和保存期间继续输入的确认 */
export function useFormDraft<T>(
  key: string,
  initial: T,
  normalize?: (value: T, latest: T) => T,
  migrate?: (cached: unknown, latest: T) => DraftEnvelope<T>,
) {
  const [draft, setDraft] = useState(() =>
    migrate
      ? migrate(loadLocal<unknown>(key, null), initial)
      : restoreDraft(
          loadLocal<T | DraftEnvelope<T> | null>(key, null),
          initial,
        ),
  );
  const current = useRef(draft);
  const active = useRef(true);
  const [latest, setLatest] = useState(initial);
  const [copies, setCopies] = useState(() =>
    loadLocal<DraftEnvelope<T>[]>(`${key}.recovery`, []),
  );
  const [notice, setNotice] = useState("");
  const conflict = draft.baseline === null || !equal(draft.baseline, latest);
  /** 输入和基线一起持久化，父组件刷新前已经有可恢复的新稿 */
  function replace(next: DraftEnvelope<T>) {
    current.current = next;
    setDraft(next);
    if (equal(next.value, next.baseline)) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(next));
  }
  useEffect(() => {
    active.current = true;
    replace(current.current);
    return () => {
      active.current = false;
    };
  }, [key]);
  /** 异步读取初始配置后重新恢复缓存，不把旧缓存绑到新基线 */
  function initialize(value: T) {
    setLatest(value);
    replace(
      restoreDraft(loadLocal<T | DraftEnvelope<T> | null>(key, null), value),
    );
  }
  /** 每次编辑同步更新引用，迟到保存确认可看到请求期间的新输入 */
  function update(value: T) {
    replace({ ...current.current, value });
  }
  /** 读取最新配置供核对，不覆盖当前输入 */
  function observe(value: T) {
    setLatest(value);
  }
  /** 切换内容前保留输入及其原基线，副本长期保留并去重 */
  function preserve(addition: DraftEnvelope<T>) {
    const next = recoveryCopies(
      loadLocal<DraftEnvelope<T>[]>(`${key}.recovery`, []),
      addition,
    );
    storage.setItem(`${key}.recovery`, JSON.stringify(next));
    setCopies(next);
  }
  /** 用户明确选择后才重设基线，双方同字段冲突保留本页并提示核对 */
  function resolve(mode: "latest" | "merge") {
    const local = current.current;
    preserve(local);
    preserve({ value: latest, baseline: latest });
    const merged =
      mode === "latest"
        ? { value: latest, conflicts: [] }
        : local.baseline === null
          ? { value: local.value, conflicts: [""] }
          : mergeDraft(local.baseline, local.value, latest);
    const value = normalize ? normalize(merged.value, latest) : merged.value;
    replace({ value, baseline: latest });
    setNotice(
      mode === "latest"
        ? "已载入最新资料，原稿保留在恢复副本中。"
        : merged.conflicts.length
          ? "双方修改了相同内容，已保留本页输入。请对照最新资料核对后保存，原稿和最新资料均已保留。"
          : "已合并双方修改，请核对后保存。原稿和最新资料均已保留。",
    );
  }
  /** 恢复副本前保留当前输入，继续按副本原基线检查冲突 */
  function recover(index: number) {
    const copy = copies[index];
    if (!copy) return;
    preserve(current.current);
    replace(structuredClone(copy));
    setNotice("已恢复副本，请核对内容；基线已变化时需再次合并。");
  }
  /** 只确认本次提交，后续输入继续作为基于确认结果的新草稿 */
  function accept(submitted: T, saved: T) {
    if (!active.current) return false;
    const confirmed = acceptDraftConfirmation(
      current.current.value,
      submitted,
      saved,
    );
    const value = normalize
      ? normalize(confirmed.value, saved)
      : confirmed.value;
    setLatest(saved);
    replace({ value, baseline: saved });
    return true;
  }
  return {
    value: draft.value,
    baseline: draft.baseline,
    latest,
    conflict,
    copies,
    notice,
    initialize,
    update,
    observe,
    resolve,
    recover,
    accept,
  };
}
