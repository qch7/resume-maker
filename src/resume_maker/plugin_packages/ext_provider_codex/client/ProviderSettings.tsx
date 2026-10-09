import { useEffect, useRef, useState } from "react";
import PathInput from "@resume-maker/plugin-sdk/shared/components/PathInput";
import { api } from "@resume-maker/plugin-sdk/shared/lib/api";
import { recoveryCopies } from "@resume-maker/plugin-sdk/shared/lib/recoveryCopies";
import {
  loadLocal,
  storage,
} from "@resume-maker/plugin-sdk/shared/lib/storage";
import type { ProviderSettings } from "@resume-maker/plugin-sdk/shared/types/index";
import type { SettingsPanelProps } from "@resume-maker/plugin-sdk/plugins/contracts";
import CodexModels from "./CodexModels";

/** 模型连接插件持有自己的设置草稿，未启用时不会读取登录或供应商 */
export default function ProviderSettingsPanel(props: SettingsPanelProps) {
  const [provider, setProvider] = useState<ProviderSettings | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [recovery, setRecovery] = useState(() =>
    recoveryCopies(
      loadLocal<ProviderSettings | ProviderSettings[] | null>(
        "rm.settings.provider.recovery",
        null,
      ),
    ),
  );
  const baseline = useRef("");
  useEffect(() => {
    if (!loaded || !provider) return;
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
        const draft = loadLocal("rm.settings.provider", value.provider);
        setProvider({ ...draft, version: draft.version ?? 0 });
        setConflict((draft.version ?? 0) !== value.provider.version);
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
      } catch (error) {
        if (error instanceof Error && "status" in error && error.status === 409)
          setConflict(true);
        setNotice(error instanceof Error ? error.message : "设置保存失败");
        throw error;
      } finally {
        setBusy(false);
      }
    });
  }
  /** 载入最新配置前保存本页副本，版本变化不会自动覆盖其他窗口 */
  async function loadLatest() {
    const latest = (await api<{ provider: ProviderSettings }>("/settings"))
      .provider;
    const copies = recoveryCopies(recovery, provider ?? undefined);
    storage.setItem("rm.settings.provider.recovery", JSON.stringify(copies));
    setRecovery(copies);
    baseline.current = JSON.stringify(latest);
    setProvider(latest);
    setConflict(false);
    setNotice("已载入最新配置，本页原稿保留在下方副本中。");
  }
  if (!provider)
    return (
      <p className={notice ? "error" : "muted"}>
        {notice || "正在读取模型连接设置"}
      </p>
    );
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
            disabled={busy || !loaded || conflict}
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
            disabled={busy || !loaded || conflict}
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
          <button disabled={busy || !loaded} onClick={() => run(loadLatest)}>
            保留副本并载入最新配置
          </button>
        </div>
        {conflict && (
          <p role="alert">
            模型配置已在其他窗口修改，请先载入最新配置，再核对并重新应用本页修改。
          </p>
        )}
        {!!recovery.length && (
          <details>
            <summary>载入前的模型配置副本</summary>
            {recovery.map((copy, index) => (
              <section key={index}>
                <p>
                  CLI：{copy.executable} · Profile：{copy.profile || "默认"} ·
                  超时：{copy.timeout_seconds} 秒
                </p>
                <CodexModels value={copy} disabled onChange={() => {}} />
              </section>
            ))}
          </details>
        )}
      </>
      {notice && <p role="status">{notice}</p>}
    </>
  );
}
