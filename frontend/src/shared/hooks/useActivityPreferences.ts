import { useEffect, useState } from "react";
import { loadLocal, storage } from "../lib/storage";
import {
  restoreActivityPreferences,
  type SavedActivityPreferences,
} from "../lib/activityPreferences";

/** 在工作台共享日志显示偏好，切换页面和打开设置时保持同步 */
export function useActivityPreferences() {
  const [preferences, setPreferences] = useState(() =>
    restoreActivityPreferences(
      loadLocal<SavedActivityPreferences | null>("rm.activity", null),
    ),
  );
  const [error, setError] = useState("");
  useEffect(() => {
    try {
      storage.setItem("rm.activity", JSON.stringify(preferences));
      setError("");
    } catch {
      setError("无法保存日志显示设置");
    }
  }, [preferences]);
  return { preferences, setPreferences, error };
}
