import { useEffect, useState } from "react";
import { api } from "@resume-maker/plugin-sdk/shared/lib/api";
import type { Conversation } from "@resume-maker/plugin-sdk/shared/types";
import type { SettingsPanelProps } from "@resume-maker/plugin-sdk/plugins/contracts";

/** 已归档会话由会话插件查询和恢复，系统设置不持有其状态 */
export default function ConversationSettings(props: SettingsPanelProps) {
  const [archived, setArchived] = useState<Conversation[]>([]);
  const [notice, setNotice] = useState("");
  const run = props.run;
  useEffect(() => {
    if (!props.active) return;
    let current = true;
    void api<Conversation[]>("/conversations/archived")
      .then((value) => {
        if (current) setArchived(value);
      })
      .catch((error: Error) => {
        if (current) setNotice(error.message);
      });
    return () => {
      current = false;
    };
  }, [props.active]);
  return (
    <>
      {" "}
      {archived.length > 0 && (
        <details>
          <summary>已归档会话 · {archived.length}</summary>
          {archived.map((c) => (
            <div className="section-heading" key={c.id}>
              <span>{c.title}</span>
              <button
                className="text-button"
                onClick={() =>
                  run(async () => {
                    await api(`/conversations/${c.id}`, "PATCH", {
                      archived: false,
                    });
                    setArchived((v) => v.filter((x) => x.id !== c.id));
                    await props.onChanged();
                  })
                }
              >
                恢复会话
              </button>
            </div>
          ))}
        </details>
      )}
      {!archived.length && <p>没有已归档会话。</p>}
      {notice && <p role="alert">{notice}</p>}
    </>
  );
}
