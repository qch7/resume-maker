import { useEffect, useRef, useState } from "react";
import PathInput from "@resume-maker/plugin-sdk/shared/components/PathInput";
import { api } from "@resume-maker/plugin-sdk/shared/lib/api";
import {
  loadLocal,
  storage,
} from "@resume-maker/plugin-sdk/shared/lib/storage";
import type { ProviderSettings } from "@resume-maker/plugin-sdk/shared/types/index";
import type { SettingsPanelProps } from "@resume-maker/plugin-sdk/plugins/contracts";
import CodexModels from "./CodexModels";

/** 模型连接插件持有自己的设置草稿，未启用时不会读取登录或供应商 */
export default function ProviderSettingsPanel(props: SettingsPanelProps) {
  const [provider, setProvider] = useState<ProviderSettings>({
    executable: "codex",
    model: "",
    reasoning_effort: "",
    profile: "",
    timeout_seconds: 1200,
    functions: {},
  });
  const [loaded, setLoaded] = useState(false);
  const baseline = useRef("");
  useEffect(() => {
    if (!loaded) return;
    if (JSON.stringify(provider) === baseline.current)
      storage.removeItem("rm.settings.provider");
    else storage.setItem("rm.settings.provider", JSON.stringify(provider));
  }, [provider, loaded]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    void api<{ provider: ProviderSettings }>("/settings")
      .then((value) => {
        baseline.current = JSON.stringify(value.provider);
        setProvider(loadLocal("rm.settings.provider", value.provider));
        setLoaded(true);
      })
      .catch((error) => setNotice(error.message));
  }, []);
  /** 先刷新工作区草稿再提交设置，异常和进度保留在当前页面 */
  function run(work: () => Promise<void>) {
    props.run(async () => {
      setBusy(true);
      setNotice("");
      try {
        await work();
      } finally {
        setBusy(false);
      }
    });
  }
  return (
    <>
      <>
        <h3>连接</h3>
        <PathInput
          label="Codex 可执行文件"
          kind="executable"
          value={provider.executable}
          disabled={busy || !loaded}
          onChange={
            /* 选择本机 CLI 启动文件，保留其他 Provider 设置 */ (value) =>
              setProvider({ ...provider, executable: value })
          }
        />
        <div className="form-grid">
          <label>
            Profile（选填）
            <input
              disabled={busy || !loaded}
              value={provider.profile}
              onChange={(e) =>
                setProvider({ ...provider, profile: e.target.value })
              }
            />
          </label>
          <label>
            单轮超时（秒）
            <input
              type="number"
              min={30}
              max={7200}
              value={provider.timeout_seconds}
              disabled={busy || !loaded}
              onChange={(e) =>
                setProvider({
                  ...provider,
                  timeout_seconds: Number(e.target.value),
                })
              }
            />
          </label>
        </div>
        <CodexModels
          value={provider}
          disabled={busy || !loaded}
          onChange={setProvider}
        />
        <div className="actions">
          <button
            disabled={busy || !loaded}
            onClick={() =>
              run(async () => {
                const saved = await api<ProviderSettings>(
                  "/settings/provider",
                  "PUT",
                  provider,
                );
                setProvider(saved);
                baseline.current = JSON.stringify(saved);
                storage.removeItem("rm.settings.provider");
                setNotice("已保存，新任务生效。");
              })
            }
          >
            保存
          </button>
          <button
            disabled={busy || !loaded}
            onClick={() =>
              run(async () => {
                const saved = await api<ProviderSettings>(
                  "/settings/provider",
                  "PUT",
                  provider,
                );
                setProvider(saved);
                baseline.current = JSON.stringify(saved);
                storage.removeItem("rm.settings.provider");
                const value = await api<{ reply: string }>(
                  "/providers/codex/check",
                  "POST",
                );
                setNotice(value.reply);
              })
            }
          >
            {busy ? "测试中…" : "测试连接"}
          </button>
        </div>
      </>
      {notice && <p role="status">{notice}</p>}
    </>
  );
}
