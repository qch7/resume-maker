import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/lib/api";
import type { RecruitmentPreferences } from "../recruitment/model";

/** 修改收藏夹导入偏好后立即保存，失败时继续显示已保存的选项 */
export default function RecruitmentSettings() {
  const [settings, setSettings] = useState<RecruitmentPreferences | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const locked = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void api<RecruitmentPreferences>(
      "/settings/recruitment",
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setSettings(value);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [attempt]);
  /** 只在服务器确认后更新选项，串行写入避免迟到响应覆盖后续选择 */
  async function save(import_policy: RecruitmentPreferences["import_policy"]) {
    if (locked.current) return;
    locked.current = true;
    setSaving(true);
    setError("");
    try {
      const value = await api<RecruitmentPreferences>(
        "/settings/recruitment",
        "PUT",
        { import_policy },
      );
      setSettings(value);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      locked.current = false;
      setSaving(false);
    }
  }
  return (
    <>
      <label>
        遇到相同 ID 的收藏
        <select
          disabled={!settings || saving}
          value={settings?.import_policy ?? "keep"}
          onChange={(event) =>
            void save(
              event.target.value as RecruitmentPreferences["import_policy"],
            )
          }
        >
          <option value="keep">保留本机内容，跳过重复项</option>
          <option value="update">使用文件内容更新重复项</option>
        </select>
      </label>
      <p className="subtle">更新会覆盖同 ID 条目的全部内容。</p>
      {saving && <p role="status">保存中…</p>}
      {error && <p role="alert">{error}</p>}
      {!settings && error && (
        <button onClick={() => setAttempt((value) => value + 1)}>
          重新加载
        </button>
      )}
    </>
  );
}
