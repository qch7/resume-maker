import { api, request } from "../shared/lib/api";
import { capabilities, type Capabilities } from "../shared/lib/capabilities";
import { flushDrafts } from "../shared/lib/draftRegistry";
import { storage } from "../shared/lib/storage";
import { clientExtensions } from "./extensions";

export const windowId = crypto.randomUUID();
let stopped = false;
const listeners = new Set<() => void>();
let notice = "";
let connecting = false;
let reloading = false;
let reloadAttempt: Promise<void> | undefined;

/** 工作台订阅配置变化和草稿刷新失败，不清除本地输入 */
export function subscribeWindow(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 获取可显示的窗口状态 */
export function windowNotice() {
  return notice;
}

/** 写入状态后同步通知壳，业务页面由壳冻结 */
function inform(value: string) {
  notice = value;
  for (const listener of listeners) listener();
}

/** 固定代次心跳，保存草稿并排空命令后再次刷新最终输入才确认 */
export async function connectWindow() {
  if (stopped || connecting) return;
  connecting = true;
  try {
    const result = await api<{
      pending_plan: string | null;
      acknowledged: boolean;
    }>("/plugins/windows", "POST", {
      id: windowId,
      generation: capabilities().generation,
    });
    if (result.pending_plan && !result.acknowledged) {
      inform("插件配置正在变更，正在保存各页面的草稿…");
      const plan = await api<{ affected: string[]; generation: number }>(
        `/plugins/plans/${result.pending_plan}`,
      );
      if (plan.generation !== capabilities().generation)
        throw new Error("插件配置已变化，请保留输入并重新协商。");
      await flushDrafts();
      await clientExtensions.drainAll();
      await flushDrafts();
      await api(`/plugins/plans/${result.pending_plan}/acknowledge`, "POST", {
        id: windowId,
        generation: capabilities().generation,
      });
      inform("草稿已保存，等待插件配置切换完成。");
    } else if (!result.pending_plan && !reloading) {
      clientExtensions.resumeAll();
      inform("");
    }
  } catch (error) {
    inform(error instanceof Error ? error.message : String(error));
  } finally {
    connecting = false;
  }
}

/** 所有页面刷新共用一次排空，调用方的保存或冲突处理只能在命令结束后执行 */
export function reloadWindow(
  prepare: () => Promise<void> = prepareWindowReload,
) {
  if (!reloadAttempt)
    reloadAttempt = finishReload(prepare).finally(() => {
      reloadAttempt = undefined;
    });
  return reloadAttempt;
}

/** 旧代次不能覆盖新资料，确认恢复副本已保存后再重新协商 */
async function prepareWindowReload() {
  try {
    await flushDrafts();
  } catch (error) {
    const latest = await api<Capabilities>("/capabilities");
    if (
      !latest.ready ||
      !Number.isSafeInteger(latest.generation) ||
      latest.generation < 1 ||
      latest.generation === capabilities().generation
    )
      throw error;
    await storage.prepareReload();
  }
}

/** 命令停止后保存最终输入，失败保留页面，由后续心跳核验能否解除冻结 */
async function finishReload(prepare: () => Promise<void>) {
  reloading = true;
  try {
    await clientExtensions.drainAll();
    await prepare();
    location.reload();
  } catch (error) {
    reloading = false;
    inform(error instanceof Error ? error.message : String(error));
    throw error;
  }
}

/** 心跳属于工作台作用域，关闭前保存成功才撤销窗口 */
export function startWindow() {
  stopped = false;
  /** 页面离开只标记断连，未完成的草稿不会被当成已经确认 */
  function leaving() {
    void request("/plugins/windows/disconnect", {
      method: "POST",
      keepalive: true,
      body: JSON.stringify({
        id: windowId,
        generation: capabilities().generation,
      }),
    }).catch(() => undefined);
  }
  window.addEventListener("pagehide", leaving);
  const timer = setInterval(() => void connectWindow(), 1500);
  void connectWindow();
  return async () => {
    stopped = true;
    window.removeEventListener("pagehide", leaving);
    clearInterval(timer);
    await flushDrafts();
    await api("/plugins/windows/close", "POST", {
      id: windowId,
      generation: capabilities().generation,
    });
  };
}
