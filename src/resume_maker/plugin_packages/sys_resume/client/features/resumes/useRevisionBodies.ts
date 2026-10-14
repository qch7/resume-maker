import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import { api, ApiError } from "@resume-maker/plugin-sdk/shared/lib/api";
import type {
  ResumeItem,
  Revision,
} from "@resume-maker/plugin-sdk/shared/types/index";

const RETRY_DELAYS = [500, 1500, 4000];

interface RevisionRead {
  running: boolean;
  done: boolean;
  failures: number;
  retryable: boolean;
  timer?: ReturnType<typeof setTimeout>;
}

/** 正文请求只跟随固定版本集合，持续编辑、其他版本入缓存不会打断在途读取 */
export function useRevisionBodies(
  items: Pick<ResumeItem, "revision_id">[],
  cache: Record<string, Revision>,
  receive: Dispatch<SetStateAction<Record<string, Revision>>>,
  onError: (error: Error) => void,
  refreshVersion = 0,
) {
  const latest = useRef({ cache, receive, onError });
  latest.current = { cache, receive, onError };
  const retry = useRef<(() => void) | null>(null);
  const key = JSON.stringify(
    [...new Set(items.map((item) => item.revision_id))].sort(),
  );
  useEffect(() => {
    const controller = new AbortController();
    const reads = new Map<string, RevisionRead>();
    /** 每个版本独立完成、退避，失败不能阻止其他正文进入缓存 */
    async function read(id: string, state: RevisionRead) {
      if (controller.signal.aborted || state.running || state.done) return;
      clearTimeout(state.timer);
      if (latest.current.cache[id]) {
        state.done = true;
        return;
      }
      state.running = true;
      try {
        const revision = await api<Revision>(
          `/revisions/${id}`,
          "GET",
          undefined,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        state.done = true;
        latest.current.receive((previous) =>
          controller.signal.aborted || previous[id]
            ? previous
            : { ...previous, [id]: revision },
        );
      } catch (failure) {
        if (controller.signal.aborted) return;
        const error =
          failure instanceof Error ? failure : new Error(String(failure));
        state.failures++;
        state.retryable =
          !(error instanceof ApiError) ||
          error.status === 408 ||
          error.status === 429 ||
          error.status >= 500;
        const delay = RETRY_DELAYS[state.failures - 1];
        if (state.retryable && delay !== undefined)
          state.timer = setTimeout(() => void read(id, state), delay);
        else latest.current.onError(error);
      } finally {
        state.running = false;
      }
    }
    /** 恢复在线、现有刷新操作只唤醒可恢复失败，不取消仍在读取的版本 */
    function wake() {
      for (const [id, state] of reads) {
        if (state.running || state.done || !state.retryable || !state.failures)
          continue;
        state.failures = 0;
        void read(id, state);
      }
    }
    for (const id of JSON.parse(key) as string[]) {
      const state = {
        running: false,
        done: false,
        failures: 0,
        retryable: true,
      };
      reads.set(id, state);
      void read(id, state);
    }
    const browser = window;
    browser.addEventListener("online", wake);
    retry.current = wake;
    return () => {
      controller.abort();
      for (const state of reads.values()) clearTimeout(state.timer);
      browser.removeEventListener("online", wake);
      if (retry.current === wake) retry.current = null;
    };
  }, [key]);
  useEffect(() => retry.current?.(), [refreshVersion]);
}
