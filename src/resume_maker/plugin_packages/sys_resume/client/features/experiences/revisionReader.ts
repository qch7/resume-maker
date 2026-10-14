import type { Revision } from "@resume-maker/plugin-sdk/shared/types/index";

/** 按不可变版本标识复用正文，取消的读取不得写入缓存 */
export function createRevisionReader(
  execute: (id: string, signal?: AbortSignal) => Promise<Revision>,
  initial: Revision[] = [],
) {
  const revisions = new Map(initial.map((revision) => [revision.id, revision]));
  return async (id: string, signal?: AbortSignal) => {
    signal?.throwIfAborted();
    const cached = revisions.get(id);
    if (cached) return cached;
    const revision = await execute(id, signal);
    signal?.throwIfAborted();
    revisions.set(id, revision);
    return revision;
  };
}
