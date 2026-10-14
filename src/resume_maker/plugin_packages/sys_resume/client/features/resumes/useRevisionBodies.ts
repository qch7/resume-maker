import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import { api } from "@resume-maker/plugin-sdk/shared/lib/api";
import type {
  ResumeItem,
  Revision,
} from "@resume-maker/plugin-sdk/shared/types/index";

/** 正文请求只跟随固定版本集合，持续编辑、其他版本入缓存不会打断在途读取 */
export function useRevisionBodies(
  items: Pick<ResumeItem, "revision_id">[],
  cache: Record<string, Revision>,
  receive: Dispatch<SetStateAction<Record<string, Revision>>>,
  onError: (error: Error) => void,
) {
  const latest = useRef({ cache, receive, onError });
  latest.current = { cache, receive, onError };
  const key = JSON.stringify(
    [...new Set(items.map((item) => item.revision_id))].sort(),
  );
  useEffect(() => {
    const controller = new AbortController();
    const missing = (JSON.parse(key) as string[]).filter(
      (id) => !latest.current.cache[id],
    );
    if (missing.length)
      void Promise.all(
        missing.map((id) =>
          api<Revision>(
            `/revisions/${id}`,
            "GET",
            undefined,
            controller.signal,
          ),
        ),
      )
        .then((values) => {
          if (!controller.signal.aborted)
            latest.current.receive((previous) =>
              controller.signal.aborted
                ? previous
                : {
                    ...previous,
                    ...Object.fromEntries(
                      values.map((revision) => [revision.id, revision]),
                    ),
                  },
            );
        })
        .catch((error) => {
          if (!controller.signal.aborted) latest.current.onError(error);
        });
    return () => controller.abort();
  }, [key]);
}
