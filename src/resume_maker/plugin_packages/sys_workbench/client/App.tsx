import { useEffect, useState, useSyncExternalStore } from "react";
import {
  clientFailures,
  pluginComponent,
  pluginPages,
} from "@resume-maker/plugin-sdk/plugins/runtime";
import {
  reloadWindow,
  startWindow,
  subscribeWindow,
  windowNotice,
} from "@resume-maker/plugin-sdk/plugins/window";
import PluginManager from "./features/plugins/PluginManager";
import CommandMenu from "@resume-maker/plugin-sdk/plugins/CommandMenu";
import PluginBoundary from "@resume-maker/plugin-sdk/plugins/PluginBoundary";

/** 壳只负责页面贡献、插件管理和窗口冻结，简历状态由系统业务插件持有 */
export default function App() {
  const Workspace = pluginComponent("workspace");
  const [manager, setManager] = useState(false);
  const [page, setPage] = useState("");
  const notice = useSyncExternalStore(subscribeWindow, windowNotice);
  useEffect(() => {
    const dispose = startWindow();
    /** 系统命令通过工作台事件打开管理页，组件状态留在壳中 */
    function openManager() {
      setManager(true);
    }
    window.addEventListener("resume-plugin-manager", openManager);
    return () => {
      window.removeEventListener("resume-plugin-manager", openManager);
      void dispose();
    };
  }, []);
  return (
    <>
      <nav className="plugin-toolbar" aria-label="插件和扩展页面">
        <button onClick={() => setManager(true)}>插件管理</button>
        <CommandMenu disabled={!!notice} />
        {pluginPages().length > 0 && (
          <button onClick={() => setPage("")}>简历工作台</button>
        )}
        {pluginPages().map((item) => (
          <button key={item.id} onClick={() => setPage(item.id)}>
            {item.title}
          </button>
        ))}
      </nav>
      {notice && (
        <div role="alert" className="plugin-notice">
          {notice}{" "}
          <button onClick={() => void reloadWindow().catch(() => undefined)}>
            重新协商并加载
          </button>
        </div>
      )}
      {[...clientFailures].map(([id, error]) => (
        <div role="alert" key={id}>
          {id}：{error}
        </div>
      ))}
      <div inert={!!notice} hidden={!!page}>
        <Workspace />
      </div>
      <div inert={!!notice}>
        {pluginPages()
          .filter((item) => item.id === page)
          .map((item) => (
            <PluginBoundary key={item.id} owner={item.id}>
              <item.component active />
            </PluginBoundary>
          ))}
      </div>
      {manager && <PluginManager onClose={() => setManager(false)} />}
    </>
  );
}
