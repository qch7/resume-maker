import { useEffect, useRef, useState } from "react";
import type { ResumeDocument } from "../../shared/types";
import {
  clientExtensions,
  jsonCopy,
  type JsonValue,
} from "../../plugins/extensions";
import PluginBoundary from "../../plugins/PluginBoundary";
import { updateExtension } from "./extensionState";

/** 编辑器消费独立副本，所有输入继续进入系统简历草稿 */
export default function ExtensionFields({
  value,
  onChange,
}: {
  value: ResumeDocument;
  onChange(value: ResumeDocument): void;
}) {
  const [error, setError] = useState("");
  const latest = useRef(value);
  latest.current = value;
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const editors = clientExtensions.list("resume.field_editors");
  const known = new Set(editors.map((item) => item.owner));
  return (
    <>
      {editors.map((item) => (
        <section className="profile-card" key={item.id}>
          <h2>{item.value.title}</h2>
          <p className="subtle">扩展资料随简历组合保存。</p>
          <PluginBoundary owner={item.owner}>
            <item.value.component
              value={
                value.extensions?.[item.owner] === undefined
                  ? undefined
                  : (jsonCopy(value.extensions[item.owner]) as JsonValue)
              }
              onChange={(next) => {
                try {
                  if (!mounted.current) return;
                  if (
                    !clientExtensions
                      .list("resume.field_editors")
                      .some((entry) => entry === item)
                  )
                    throw new Error("资料编辑器已经停用。");
                  if (
                    JSON.stringify(latest.current.extensions?.[item.owner]) !==
                    JSON.stringify(value.extensions?.[item.owner])
                  )
                    throw new Error("此扩展字段已被后续输入修改。");
                  const updated = updateExtension(
                    latest.current,
                    item.owner,
                    next,
                  );
                  latest.current = updated;
                  onChange(updated);
                  setError("");
                } catch {
                  setError("扩展输入已过期或不符合格式限制，现有草稿仍保留。");
                }
              }}
            />
          </PluginBoundary>
        </section>
      ))}
      {Object.keys(value.extensions ?? {})
        .filter((owner) => !known.has(owner))
        .map((owner) => (
          <p key={owner} className="subtle">
            {owner} 的资料已保留，启用对应编辑器后可继续编辑。
          </p>
        ))}
      {error && <p role="alert">{error}</p>}
    </>
  );
}
