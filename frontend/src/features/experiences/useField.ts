import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../shared/lib/api";
import { loadLocal } from "../../shared/lib/storage";
import type { ProjectDetail, Working } from "../../shared/types/index";

import { registerDraft } from "../../shared/lib/draftRegistry";

/** 清理指定项目版本的本机字段缓存以免发布后恢复旧草稿 */
export function clearLocalDrafts(project: string, revision: string) {
  const prefix = `rm.field.${project}.${revision}.`;
  for (const key of Object.keys(localStorage))
    if (key.startsWith(prefix)) localStorage.removeItem(key);
}

/** 管理单字段草稿的本机恢复、串行写入、防抖保存和并发冲突处理 */
export function useField<T>(
  project: string,
  revision: string,
  field: string,
  initial: T,
  initialVersion: number,
  isChanged: (value: T) => boolean,
) {
  const key = `rm.field.${project}.${revision}.${field}`;
  const [cached] = useState(() =>
    loadLocal<{ value: T; version: number } | null>(key, null),
  );
  const [value, setValue] = useState<T>(() => cached?.value ?? initial);
  const [status, setStatus] = useState("");
  const [conflict, setConflict] = useState(false);
  const [failed, setFailed] = useState(false);
  const current = useRef(value),
    saved = useRef(JSON.stringify(initial)),
    version = useRef(cached?.version ?? initialVersion);
  const chain = useRef(Promise.resolve());
  const mounted = useRef(true);
  /** 串行刷新最新输入且只有写入成功后才推进已保存值和草稿版本 */
  const flush = () => {
    const next = chain.current
      .catch(/* 上次错误已显示，恢复后续写入 */ () => {})
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
          if (mounted.current) {
            setFailed(false);
            setStatus("草稿已保存，待提交");
          }
        } catch (error) {
          if (
            error instanceof ApiError &&
            error.status === 409 &&
            mounted.current
          )
            setConflict(true);
          if (mounted.current) {
            setFailed(true);
            setStatus((error as Error).message);
          }
          throw error;
        }
      });
    chain.current = next;
    return next;
  };
  useEffect(() => {
    mounted.current = true;
    const unregister = registerDraft(key, flush);
    return () => {
      mounted.current = false;
      unregister();
      void flush().catch(/* 上次错误已显示，恢复后续写入 */ () => {});
    };
    // 项目、修订或服务器草稿变化时重新挂载字段以免串用旧版本状态
  }, [key]);
  useEffect(() => {
    const timer = setTimeout(
      /* 延迟执行保存或提示清理，减少频繁更新 */ () =>
        void flush().catch(/* 上次错误已显示，恢复后续写入 */ () => {}),
      450,
    );
    return () => clearTimeout(timer);
  }, [value]);
  /** 立即更新编辑值和本地恢复副本，再由防抖逻辑提交服务器草稿 */
  function update(next: T) {
    current.current = next;
    setValue(next);
    setStatus("已保留到本机，正在同步草稿");
    localStorage.setItem(
      key,
      JSON.stringify({ value: next, version: version.current }),
    );
  }
  /** 保留本机恢复副本后载入服务器最新草稿，重置冲突状态和版本号 */
  async function reloadRemote() {
    await chain.current.catch(/* 上次错误已显示，恢复后续写入 */ () => {});
    try {
      const remote = await api<ProjectDetail>(
        `/projects/${project}?revision_id=${revision}`,
      );
      const content = remote.working.content;
      const { highlights: _highlights, ...meta } = content;
      const next = (
        field === "meta"
          ? meta
          : field === "order"
            ? content.highlights.map(
                /* 恢复完整服务器排序 */ (point) => point.id,
              )
            : content.highlights.find((h) => h.id === field.slice(10))
      ) as T | undefined;
      // 覆盖冲突的本机编辑前保存恢复副本，便于用户取回未合并的内容
      localStorage.setItem(`${key}.recovery`, JSON.stringify(current.current));
      current.current = next ?? initial;
      saved.current = JSON.stringify(current.current);
      version.current =
        remote.working.drafts.find((d) => d.field === field)?.version ?? 0;
      setValue(current.current);
      setConflict(false);
      setFailed(false);
      setStatus("已载入服务器草稿");
      localStorage.removeItem(key);
      return current.current;
    } catch (e) {
      setStatus((e as Error).message);
    }
  }
  return {
    value,
    update,
    flush,
    status: failed || conflict || isChanged(value) ? status : "",
    version,
    conflict,
    reloadRemote,
  };
}
