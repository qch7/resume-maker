/** 正常轮询保持原频率，连续失败退避且恢复事件立即核对 */
export function createStatePolling(
  execute: (signal: AbortSignal) => Promise<void>,
  onError: (failure: unknown) => void,
  interval = 1600,
) {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let running = false;
  let requested = false;
  let failures = 0;

  /** 同一循环最多一个读取，恢复期间合并重复唤醒 */
  async function poll() {
    if (controller.signal.aborted) return;
    if (running) {
      requested = true;
      return;
    }
    clearTimeout(timer);
    running = true;
    try {
      await execute(controller.signal);
      failures = 0;
    } catch (failure) {
      if (!controller.signal.aborted) {
        failures++;
        onError(failure);
      }
    } finally {
      running = false;
      if (!controller.signal.aborted) {
        const delay = requested
          ? 0
          : Math.min(30000, interval * 2 ** Math.min(failures, 5));
        requested = false;
        timer = setTimeout(poll, delay);
      }
    }
  }
  void poll();
  return {
    /** 重新在线或恢复可见时保持已有请求并安排一次最新读取 */
    wake() {
      failures = 0;
      void poll();
    },
    /** 离开工作台后取消读取及后继计时器 */
    stop() {
      controller.abort();
      clearTimeout(timer);
    },
  };
}

/** 页面隐藏仍按原频率同步，恢复可见或在线时立即核对 */
export function bindStatePolling(
  polling: { wake(): void },
  browser: Pick<Window, "addEventListener" | "removeEventListener"> = window,
  page: Pick<
    Document,
    "visibilityState" | "addEventListener" | "removeEventListener"
  > = document,
) {
  /** 隐藏事件保留必要后台同步，恢复可见再唤醒 */
  function visible() {
    if (page.visibilityState === "visible") polling.wake();
  }
  browser.addEventListener("online", polling.wake);
  page.addEventListener("visibilitychange", visible);
  return () => {
    browser.removeEventListener("online", polling.wake);
    page.removeEventListener("visibilitychange", visible);
  };
}
