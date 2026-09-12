import { useEffect, useRef, useState } from "react";
import { api, ApiError, loadLocal } from "./api";
import type { ProjectDetail, Working } from "./types";

const pending = new Map<string, () => Promise<void>>();
export function registerDraft(key: string, flush: () => Promise<void>) {
  pending.set(key, flush);
  return () => {
    pending.delete(key);
  };
}
export const flushDrafts = () =>
  Promise.all([...pending.values()].map((flush) => flush()));
export function clearLocalDrafts(project: string, revision: string) {
  const prefix = `rm.field.${project}.${revision}.`;
  for (const key of Object.keys(localStorage))
    if (key.startsWith(prefix)) localStorage.removeItem(key);
}

export function useField<T>(
  project: string,
  revision: string,
  field: string,
  initial: T,
  initialVersion: number,
  onDirty?: () => void,
) {
  const key = `rm.field.${project}.${revision}.${field}`;
  const [cached] = useState(() =>
    loadLocal<{ value: T; version: number } | null>(key, null),
  );
  const [value, setValue] = useState<T>(() => cached?.value ?? initial);
  const [status, setStatus] = useState("");
  const [conflict, setConflict] = useState(false);
  const current = useRef(value),
    saved = useRef(JSON.stringify(initial)),
    version = useRef(cached?.version ?? initialVersion);
  const chain = useRef(Promise.resolve());
  const mounted = useRef(true);
  const flush = () => {
    const next = chain.current
      .catch(() => {})
      .then(async () => {
        const snapshot = current.current,
          encoded = JSON.stringify(snapshot);
        if (encoded === saved.current) return;
        if (mounted.current) setStatus("保存草稿中");
        try {
          const response = await api<Working>(
            `/projects/${project}/draft`,
            "PUT",
            {
              base_revision: revision,
              field,
              value: snapshot,
              version: version.current,
            },
          );
          version.current =
            response.drafts.find((d) => d.field === field)?.version ??
            version.current;
          saved.current = encoded;
          if (JSON.stringify(current.current) === encoded)
            localStorage.removeItem(key);
          else
            localStorage.setItem(
              key,
              JSON.stringify({
                value: current.current,
                version: version.current,
              }),
            );
          if (mounted.current) setStatus("草稿已保存");
        } catch (error) {
          if (
            error instanceof ApiError &&
            error.status === 409 &&
            mounted.current
          )
            setConflict(true);
          if (mounted.current) setStatus((error as Error).message);
          throw error;
        }
      });
    chain.current = next;
    return next;
  };
  useEffect(() => {
    mounted.current = true;
    if (cached && JSON.stringify(cached.value) !== JSON.stringify(initial))
      onDirty?.();
    pending.set(key, flush);
    return () => {
      mounted.current = false;
      pending.delete(key);
      void flush().catch(() => {});
    };
    // A field is remounted when its project, revision or server draft changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    const timer = setTimeout(() => void flush().catch(() => {}), 450);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  function update(next: T) {
    onDirty?.();
    current.current = next;
    setValue(next);
    setStatus("有未保存修改");
    localStorage.setItem(
      key,
      JSON.stringify({ value: next, version: version.current }),
    );
  }
  async function reloadRemote() {
    await chain.current.catch(() => {});
    try {
      const remote = await api<ProjectDetail>(
        `/projects/${project}?revision_id=${revision}`,
      );
      const content = remote.working.content;
      const { highlights: _highlights, ...meta } = content;
      const next = (
        field === "meta"
          ? meta
          : content.highlights.find((h) => h.id === field.slice(10))
      ) as T | undefined;
      // Keep a recovery copy before the user discards a conflicting local edit.
      localStorage.setItem(`${key}.recovery`, JSON.stringify(current.current));
      current.current = next ?? initial;
      saved.current = JSON.stringify(current.current);
      version.current =
        remote.working.drafts.find((d) => d.field === field)?.version ?? 0;
      setValue(current.current);
      setConflict(false);
      setStatus("已载入服务器草稿");
      localStorage.removeItem(key);
      return current.current;
    } catch (e) {
      setStatus((e as Error).message);
    }
  }
  return { value, update, flush, status, version, conflict, reloadRemote };
}
