export interface PreviewState<T> {
  key: string | null;
  status: "idle" | "waiting" | "rendering" | "ready" | "error";
  result?: { key: string; value: T };
  error?: string;
}

/** 合并连续输入；已有 Word 请求完成后只处理最新资料，不中断请求制造后台排队。 */
export function createPreviewQueue<T>(
  execute: (key: string, signal: AbortSignal) => Promise<T>,
  emit: (state: PreviewState<T>) => void,
  delay = 1000,
) {
  let state: PreviewState<T> = { key: null, status: "idle" };
  let generation = 0;
  let ready = false;
  let busy = false;
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const controller = new AbortController();

  /** 仅发布最新任务的状态，卸载后的完成事件不能再修改页面。 */
  function publish(value: PreviewState<T>) {
    state = value;
    if (!disposed) emit(state);
  }

  /** 每次最多一个真实请求；过时响应只释放队列，不冒充新资料。 */
  async function drain() {
    if (disposed || busy || !ready || state.key === null) return;
    const current = generation;
    const key = state.key;
    ready = false;
    busy = true;
    publish({ ...state, status: "rendering" });
    try {
      const value = await execute(key, controller.signal);
      if (!disposed && generation === current)
        publish({ key, status: "ready", result: { key, value } });
    } catch (error) {
      if (!disposed && generation === current)
        publish({
          ...state,
          status: "error",
          error: error instanceof Error ? error.message : String(error),
        });
    } finally {
      busy = false;
      void drain();
    }
  }

  return {
    /** 相同资料无需重排版；显式重试允许绕过失败状态。 */
    submit(key: string | null, force = false) {
      if (disposed || (state.key === key && !force)) return;
      generation++;
      ready = false;
      clearTimeout(timer);
      publish({
        key,
        status: key === null ? "idle" : "waiting",
        result: key === null ? undefined : state.result,
      });
      if (key !== null)
        timer = setTimeout(
          /* 输入停顿后才排版，合并中间按键。 */ () => {
            ready = true;
            void drain();
          },
          delay,
        );
    },
    /** 仅卸载时取消网络读取，并阻止迟到结果与后续任务。 */
    dispose() {
      disposed = true;
      clearTimeout(timer);
      controller.abort();
    },
  };
}
