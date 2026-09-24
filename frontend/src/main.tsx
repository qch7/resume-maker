import { createRoot } from "react-dom/client";
import App from "./app/App";
import { reportClientError } from "./shared/lib/api";
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
/** 数据库草稿恢复完成后才挂载表单，避免空白初值覆盖保存内容 */
async function start() {
  try {
    await initializeStorage();
    const theme = storage.getItem("rm.theme");
    if (theme) document.documentElement.dataset.theme = theme;
    root.render(
      <>
        <App />
        <PersistenceStatus />
      </>,
    );
  } catch {
    root.render(
      <main>
        <p>本机资料加载失败，连接恢复后可重试。</p>
        <button onClick={() => void start()}>重新加载</button>
      </main>,
    );
  }
}
void start();
