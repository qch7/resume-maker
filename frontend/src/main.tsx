import { createRoot } from "react-dom/client";
import { HOST_RECONNECT_MS } from "./shared/lib/timing";
import { initializePlugins, pluginComponent } from "./plugins/runtime";
import { ApiError, reportClientError } from "./shared/lib/api";
import { initializeStorage, storage } from "./shared/lib/storage";
import PersistenceStatus from "./shared/components/PersistenceStatus";
import "./styles/index.css";

window.addEventListener("error", (event) =>
  reportClientError(
    "uncaught_error",
    event.error ?? event.message,
    event.filename,
  ),
);
window.addEventListener("unhandledrejection", (event) =>
  reportClientError("unhandled_rejection", event.reason),
);

window.addEventListener("beforeunload", (event) => {
  if (storage.warnBeforeUnload()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener(
  "online",
  () => void storage.flush().catch(() => undefined),
);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden")
    void storage.flush().catch(() => undefined);
});

const root = createRoot(document.getElementById("root")!);
let starting = false;
let retry: ReturnType<typeof setTimeout> | undefined;
/** 数据库草稿恢复完成后才挂载表单，避免空白初值覆盖保存内容 */
async function start() {
  if (starting) return;
  starting = true;
  clearTimeout(retry);
  try {
    await initializePlugins();
    await initializeStorage();
    const App = pluginComponent("workbench");
    const theme = storage.getItem("rm.theme");
    if (theme) document.documentElement.dataset.theme = theme;
    root.render(
      <>
        <App />
        <PersistenceStatus />
      </>,
    );
  } catch (failure) {
    const reconnect =
      failure instanceof TypeError ||
      (failure instanceof ApiError && [409, 503].includes(failure.status));
    root.render(
      <main>
        <p>
          {reconnect
            ? "服务正在启动，连接恢复后会自动打开工作台。"
            : "本机资料加载失败，连接恢复后可重试。"}
        </p>
        <button onClick={() => void start()}>重新加载</button>
      </main>,
    );
    if (reconnect) retry = setTimeout(() => void start(), HOST_RECONNECT_MS);
  } finally {
    starting = false;
  }
}
void start();
