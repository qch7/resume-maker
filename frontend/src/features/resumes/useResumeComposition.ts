import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "../../shared/lib/api";
import { loadLocal } from "../../shared/lib/storage";
import type { Export, Resume, Revision, State } from "../../shared/types";

export const NEW_RESUME: Resume = {
  id: "",
  name: "我的简历",
  template_id: null,
  items: [],
  version: 0,
};

interface Options {
  state: State;
  activeProject: string;
  revisionId: string;
  revisionCache: Record<string, Revision>;
  setRevisionCache: Dispatch<SetStateAction<Record<string, Revision>>>;
  reload: () => Promise<void>;
  run: (work: () => Promise<void>) => void;
  notify: (message: { text: string; error?: boolean }) => void;
}

/** 维护简历组合草稿、固定版本选择、历史导出和保存导出操作。 */
export function useResumeComposition({
  state,
  activeProject,
  revisionId,
  revisionCache,
  setRevisionCache,
  reload,
  run,
  notify,
}: Options) {
  const [draft, setDraft] = useState<Resume>(
    /* 仅在首次挂载时读取缓存或计算初始状态。 */ () =>
      loadLocal("rm.resume.last", NEW_RESUME),
  );
  const [exported, setExported] = useState<Export | null>(null),
    [exporting, setExporting] = useState(false);
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      if (!draft.id) {
        setExported(null);
        return;
      }
      const controller = new AbortController();
      void api<Export[]>(
        `/resumes/${draft.id}/exports`,
        "GET",
        undefined,
        controller.signal,
      )
        .then(
          /* 在异步操作成功后同步结果及相关状态。 */ (rows) => {
            if (!controller.signal.aborted)
              setExported(
                /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
                  previous,
                ) =>
                  previous?.resume_id === draft.id &&
                  previous.created_at > (rows[0]?.created_at ?? "")
                    ? previous
                    : (rows[0] ?? null),
              );
          },
        )
        .catch(
          /* 保留可展示的失败原因，并避免已取消请求更新页面。 */ (error) => {
            if (!controller.signal.aborted)
              notify({ text: error.message, error: true });
          },
        );
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        controller.abort();
    },
    [draft.id, notify],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      localStorage.setItem("rm.resume.last", JSON.stringify(draft));
      localStorage.setItem(
        `rm.resume.${draft.id || "new"}`,
        JSON.stringify(draft),
      );
    },
    [draft],
  );
  /** 显式更新当前项目的引用版本，并保留仍属于该版本的亮点选择。 */
  function applyVersion() {
    const revision = revisionCache[revisionId];
    if (!revision) return;
    const previous = draft.items.find(
      /* 定位与当前标识或条件匹配的条目。 */ (i) =>
        i.project_id === activeProject,
    );
    const validIds = revision.content.highlights.map(
      /* 逐项转换数据，保留当前业务需要的字段。 */ (h) => h.id,
    );
    const hadHighlights =
      previous &&
      revisionCache[previous.revision_id]?.content.highlights.length;
    const item = {
      project_id: activeProject,
      revision_id: revisionId,
      highlight_ids:
        previous && hadHighlights
          ? previous.highlight_ids.filter(
              /* 保留满足当前范围或有效性条件的条目。 */ (id) =>
                validIds.includes(id),
            )
          : validIds,
    };
    setDraft({
      ...draft,
      items: previous
        ? draft.items.map(
            /* 逐项转换数据，保留当前业务需要的字段。 */ (i) =>
              i.project_id === activeProject ? item : i,
          )
        : [...draft.items, item],
    });
  }
  /** 切换项目是否加入简历；新增时读取并固定其当前已保存版本。 */
  function toggleProject(id: string) {
    run(
      /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
        if (
          draft.items.some(
            /* 检查条目是否满足当前选择或校验条件。 */ (i) =>
              i.project_id === id,
          )
        ) {
          setDraft(
            /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (
              value,
            ) => ({
              ...value,
              items: value.items.filter(
                /* 保留满足当前范围或有效性条件的条目。 */ (i) =>
                  i.project_id !== id,
              ),
            }),
          );
          return;
        }
        const head = state.projects.find(
          /* 定位与当前标识或条件匹配的条目。 */ (p) => p.id === id,
        )!.head_revision;
        const revision =
          revisionCache[head] ?? (await api<Revision>(`/revisions/${head}`));
        setRevisionCache(
          /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (v) => ({
            ...v,
            [head]: revision,
          }),
        );
        setDraft(
          /* 基于最近一次状态计算新值，避免异步闭包覆盖后续修改。 */ (value) =>
            value.items.some(
              /* 检查条目是否满足当前选择或校验条件。 */ (i) =>
                i.project_id === id,
            )
              ? value
              : {
                  ...value,
                  items: [
                    ...value.items,
                    {
                      project_id: id,
                      revision_id: head,
                      highlight_ids: revision.content.highlights.map(
                        /* 逐项转换数据，保留当前业务需要的字段。 */ (h) =>
                          h.id,
                      ),
                    },
                  ],
                },
        );
      },
    );
  }
  /** 切换亮点选择，拒绝引用尚未存在于简历固定版本中的条目。 */
  function toggleHighlight(id: string) {
    const current = draft.items.find(
      /* 定位与当前标识或条件匹配的条目。 */ (i) =>
        i.project_id === activeProject,
    );
    if (!current) {
      notify({ text: "请先将该经历版本用于当前简历。" });
      return;
    }
    if (
      !revisionCache[current.revision_id]?.content.highlights.some(
        /* 检查条目是否满足当前选择或校验条件。 */ (h) => h.id === id,
      )
    ) {
      notify({
        text: "这条亮点尚未保存在简历引用的版本中，请先保存并更新组合。",
      });
      return;
    }
    setDraft({
      ...draft,
      items: draft.items.map(
        /* 逐项转换数据，保留当前业务需要的字段。 */ (i) =>
          i.project_id === activeProject
            ? {
                ...i,
                highlight_ids: i.highlight_ids.includes(id)
                  ? i.highlight_ids.filter(
                      /* 保留满足当前范围或有效性条件的条目。 */ (x) =>
                        x !== id,
                    )
                  : [...i.highlight_ids, id],
              }
            : i,
      ),
    });
  }
  /** 携带组合版本号保存模板和固定引用，并刷新服务器聚合数据。 */
  async function saveComposition() {
    const body = {
      name: draft.name,
      template_id: draft.template_id,
      items: draft.items,
      version: draft.version,
    };
    const saved = await api<Resume>(
      draft.id ? `/resumes/${draft.id}` : "/resumes",
      draft.id ? "PUT" : "POST",
      body,
    );
    setDraft(saved);
    await reload();
    return saved;
  }
  /** 先保存组合再导出文档，始终在完成或失败后清除导出中状态。 */
  async function exportResume() {
    setExporting(true);
    try {
      const saved = await saveComposition();
      const result = await api<Export>(`/resumes/${saved.id}/exports`, "POST");
      setExported(result);
      notify({
        text: result.pages
          ? `Word 已生成，共 ${result.pages} 页。`
          : "Word 已生成，可下载；渲染结果见右侧。",
      });
    } finally {
      setExporting(false);
    }
  }

  return {
    draft,
    setDraft,
    exported,
    setExported,
    exporting,
    applyVersion,
    toggleProject,
    toggleHighlight,
    saveComposition,
    exportResume,
  };
}
