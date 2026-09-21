export interface PreviewState<T> {
  key: string | null;
  status: "idle" | "waiting" | "rendering" | "ready" | "error";
  result?: { key: string; value: T };
  error?: string;
}

/** 等待当前 Word 请求完成后处理最新输入 */
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

  /** 仅发布最新任务的状态，卸载后的完成事件不能再修改页面 */
  function publish(value: PreviewState<T>) {
    state = value;
    if (!disposed) emit(state);
  }

  /** 串行执行预览请求并丢弃过时响应 */
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
    /** 相同资料无需重排版，显式重试允许绕过失败状态 */
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
          /* 输入停顿后才排版，合并中间按键 */ () => {
            ready = true;
            void drain();
          },
          delay,
        );
    },
    /** 仅卸载时取消网络读取并阻止迟到结果和后续任务 */
    dispose() {
      disposed = true;
      clearTimeout(timer);
      controller.abort();
    },
  };
}
