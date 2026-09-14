import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { api } from "../../shared/lib/api";
import { loadLocal } from "../../shared/lib/storage";
import type {
  Experience,
  Export,
  Resume,
  Revision,
  State,
} from "../../shared/types";
import { buildLivePreview } from "./livePreview";
import { newDocument } from "../profile/document";
import { templateForDocument } from "../templates/mapping";
import { entryComposition } from "../profile/entry";
import { personalComposition } from "../profile/personal";
import {
  orderCompositionHighlights,
  orderedHighlightIds,
  toggleHighlightSelection,
  acceptSavedComposition,
} from "./composition";

export const NEW_RESUME: Resume = {
  id: "",
  name: "我的简历",
  template_id: null,
  items: [],
  version: 0,
  document: newDocument(),
};

interface Options {
  state: State;
  activeProject: string;
  revisionId: string;
  revisionCache: Record<string, Revision>;
  workingPreviews: Record<string, Experience>;
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
  workingPreviews,
  setRevisionCache,
  reload,
  run,
  notify,
}: Options) {
  const [storedDraft, setDraft] = useState<Resume>(
    /* 仅在首次挂载时读取缓存或计算初始状态。 */ () =>
      loadLocal("rm.resume.v2.last", NEW_RESUME),
  );
  const draft = useMemo(
    /* 固定组合与编辑区分别维护顺序，保证取消草稿后预览和导出一致。 */ () =>
      orderCompositionHighlights(storedDraft, revisionCache),
    [storedDraft, revisionCache],
  );
  const currentDraft = useRef(draft);
  currentDraft.current = draft;
  const { sources: previewSources, changed: previewChanged } = useMemo(
    /* 工作副本只覆盖预览层，仍由用户明确提交和更新简历引用。 */ () =>
      buildLivePreview(
        draft,
        revisionCache,
        workingPreviews,
        activeProject,
        revisionId,
      ),
    [draft, revisionCache, workingPreviews, activeProject, revisionId],
  );
  const [exported, setExported] = useState<Export | null>(null),
    [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const savingResume = useRef(false);
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
      try {
        localStorage.setItem("rm.resume.v2.last", JSON.stringify(draft));
        localStorage.setItem(
          `rm.resume.v2.${draft.id || "new"}`,
          JSON.stringify(draft),
        );
      } catch {
        notify({
          text: "浏览器草稿空间不足，请点击“保存组合”将当前资料保存到本机数据库。",
          error: true,
        });
      }
    },
    [draft, notify],
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
          ? orderedHighlightIds(
              revision.content.highlights,
              previous.highlight_ids,
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
        const head =
          id === activeProject
            ? revisionId
            : state.projects.find(
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
                      highlight_ids: (
                        workingPreviews[head] ?? revision.content
                      ).highlights.map(
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
  /** 在实时工作副本中切换亮点；新增草稿条目可以先预览，提交后再保存组合。 */
  function toggleHighlight(id: string) {
    const current = draft.items.find(
      /* 定位与当前标识或条件匹配的条目。 */ (i) =>
        i.project_id === activeProject,
    );
    if (!current) {
      notify({ text: "请先将该经历版本用于当前简历。" });
      return;
    }
    const source =
      previewSources[activeProject] ?? revisionCache[current.revision_id];
    if (
      !source?.content.highlights.some(
        /* 检查条目是否满足当前选择或校验条件。 */ (h) => h.id === id,
      )
    ) {
      notify({
        text: "这条亮点已不在当前编辑内容中，请刷新后重试。",
      });
      return;
    }
    setDraft(
      /* 使用最新选择处理连续勾选，避免覆盖其他组合修改。 */ (value) => ({
        ...value,
        items: value.items.map(
          /* 逐项转换数据，保留当前业务需要的字段。 */ (i) =>
            i.project_id === activeProject
              ? {
                  ...i,
                  highlight_ids: toggleHighlightSelection(
                    source.content.highlights,
                    i.highlight_ids,
                    id,
                  ),
                }
              : i,
        ),
      }),
    );
  }
  /** 携带组合版本号保存模板和固定引用，并刷新服务器聚合数据。 */
  async function saveComposition() {
    if (savingResume.current) throw new Error("简历资料正在保存，请稍候。");
    if (previewChanged)
      throw new Error(
        "预览已跟随编辑区更新，请先提交修改并点击“用于当前简历”，再保存或导出组合。",
      );
    savingResume.current = true;
    try {
      const body = {
        name: draft.name,
        template_id: draft.template_id,
        items: draft.items,
        version: draft.version,
        document: draft.document,
      };
      const saved = await api<Resume>(
        draft.id ? `/resumes/${draft.id}` : "/resumes",
        draft.id ? "PUT" : "POST",
        body,
      );
      setDraft(
        /* 保存期间的新输入继续留在草稿，切换方案后不抢回焦点。 */ (current) =>
          acceptSavedComposition(current, draft, saved),
      );
      await reload();
      return saved;
    } finally {
      savingResume.current = false;
    }
  }
  /** 单独保存顶部资料，以方案版本检查并发，并保留其他栏目的本机草稿。 */
  async function savePersonalInfo() {
    if (savingResume.current) throw new Error("简历资料正在保存，请稍候。");
    if (exporting || deleting)
      throw new Error("请等待当前简历操作完成后再保存。");
    savingResume.current = true;
    try {
      const submitted = personalComposition(
        { ...draft, template_id: templateForDocument(draft, state.templates) },
        state.resumes.find(
          /* 只读取当前方案已经保存的栏目和项目引用。 */ (resume) =>
            resume.id === draft.id,
        ),
      );
      const saved = await api<Resume>(
        submitted.id ? `/resumes/${submitted.id}` : "/resumes",
        submitted.id ? "PUT" : "POST",
        {
          name: submitted.name,
          template_id: submitted.template_id,
          items: submitted.items,
          version: submitted.version,
          document: submitted.document,
        },
      );
      setDraft(
        /* 基本信息独立采用保存结果，保留其他栏目与请求后的新输入。 */ (
          current,
        ) => acceptSavedComposition(current, submitted, saved),
      );
      await reload();
    } finally {
      savingResume.current = false;
    }
  }
  /** 单独保存栏目中的一条经历，不提交其他资料草稿，所有保存共用并发保护。 */
  async function saveSectionEntry(sectionId: string, entryId: string) {
    if (savingResume.current) throw new Error("简历资料正在保存，请稍候。");
    if (exporting || deleting)
      throw new Error("请等待当前简历操作完成后再保存。");
    savingResume.current = true;
    try {
      const submitted = entryComposition(
        { ...draft, template_id: templateForDocument(draft, state.templates) },
        state.resumes.find(
          /* 从已保存方案中读取其他资料。 */ (resume) => resume.id === draft.id,
        ),
        sectionId,
        entryId,
      );
      const saved = await api<Resume>(
        submitted.id ? `/resumes/${submitted.id}` : "/resumes",
        submitted.id ? "PUT" : "POST",
        {
          name: submitted.name,
          template_id: submitted.template_id,
          items: submitted.items,
          version: submitted.version,
          document: submitted.document,
        },
      );
      setDraft(
        /* 推进保存版本，保留其他草稿及后续输入。 */ (current) =>
          acceptSavedComposition(current, submitted, saved),
      );
      await reload();
    } finally {
      savingResume.current = false;
    }
  }
  /** 删除指定方案并清理本地草稿，选择剩余方案或回到空白组合。 */
  async function deleteComposition(resume: Resume) {
    if (!resume.id || deleting || exporting || savingResume.current) return;
    setDeleting(true);
    try {
      await api(`/resumes/${resume.id}?version=${resume.version}`, "DELETE");
      localStorage.removeItem(`rm.resume.v2.${resume.id}`);
      const remaining = state.resumes.find(
        /* 按方案列表顺序选择下一个仍存在的方案。 */ (item) =>
          item.id !== resume.id,
      );
      const next = remaining
        ? loadLocal(`rm.resume.v2.${remaining.id}`, remaining)
        : { ...NEW_RESUME, document: newDocument() };
      setDraft(
        /* 删除期间若已经切换方案，保留用户当前选择。 */ (current) =>
          current.id === resume.id ? next : current,
      );
      setExported(
        /* 清除被删除方案的预览，不覆盖其他方案的导出。 */ (current) =>
          current?.resume_id === resume.id ? null : current,
      );
      await reload();
      notify({ text: `已删除简历方案“${resume.name}”。` });
    } finally {
      setDeleting(false);
    }
  }
  /** 先保存组合再导出文档，始终在完成或失败后清除导出中状态。 */
  async function exportResume() {
    setExporting(true);
    try {
      const saved = await saveComposition();
      const result = await api<Export>(`/resumes/${saved.id}/exports`, "POST");
      if (currentDraft.current.id === saved.id) setExported(result);
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
    deleting,
    applyVersion,
    toggleProject,
    toggleHighlight,
    saveComposition,
    savePersonalInfo,
    saveSectionEntry,
    deleteComposition,
    exportResume,
    previewSources,
    previewChanged,
  };
}
