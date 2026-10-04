import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/lib/api";
import type { ResumeSection } from "../../shared/types";
import { addSource, type SourceItem } from "./sourceState";

interface Source {
  id: string;
  title: string;
}

/** 有界读取公开资料来源，选中内容继续沿用栏目草稿及正式保存 */
export default function SourcePicker({
  section,
  onChange,
}: {
  section: ResumeSection;
  onChange(section: ResumeSection): void;
}) {
  const [opened, setOpened] = useState(false);
  const [sources, setSources] = useState<Source[]>([]);
  const [provider, setProvider] = useState("");
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [page, setPage] = useState<{
    items: SourceItem[];
    cursor: string | null;
  }>({ items: [], cursor: null });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadedFor, setLoadedFor] = useState("");
  const requested = JSON.stringify([provider, query, cursor]);
  const latest = useRef(section);
  latest.current = section;
  useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    void api<Source[]>("/resume-sources", "GET", undefined, controller.signal)
      .then((values) => {
        if (controller.signal.aborted) return;
        setSources(values);
        setProvider((previous) =>
          values.some((value) => value.id === previous)
            ? previous
            : (values[0]?.id ?? ""),
        );
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [opened]);
  useEffect(() => {
    if (!opened || !provider) return;
    const controller = new AbortController();
    setLoading(true);
    setPage({ items: [], cursor: null });
    setError("");
    const params = new URLSearchParams({ provider, query, limit: "50" });
    if (cursor) params.set("cursor", cursor);
    void api<typeof page>(
      `/resume-source-items?${params}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) {
          setPage(value);
          setLoadedFor(JSON.stringify([provider, query, cursor]));
        }
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [opened, provider, query, cursor]);
  return (
    <div>
      <button className="text-button" onClick={() => setOpened(!opened)}>
        {opened ? "收起资料来源" : "从资料来源添加"}
      </button>
      {opened && (
        <div aria-label={`${section.title}的资料来源`}>
          <select
            aria-label="资料来源"
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value);
              setCursor(null);
            }}
          >
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.title}
              </option>
            ))}
          </select>
          <input
            aria-label="搜索来源资料"
            value={query}
            maxLength={200}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(null);
            }}
            placeholder="搜索已核对的内容"
          />
          {error && <p role="alert">{error}</p>}
          {loading && <p>读取中…</p>}
          {!loading && !sources.length && (
            <p className="subtle">启用资料来源插件后，可在这里选择内容。</p>
          )}
          {!loading && provider && !page.items.length && (
            <p className="subtle">没有匹配的已核对资料。</p>
          )}
          {(loadedFor === requested ? page.items : []).map((item) => (
            <div key={item.id} className="row">
              <span>
                {item.title || "未命名资料"} {item.subtitle} {item.period}
              </span>
              <button
                onClick={() => {
                  try {
                    const updated = addSource(
                      latest.current,
                      provider,
                      item,
                      crypto.randomUUID(),
                    );
                    latest.current = updated;
                    onChange(updated);
                    setError("");
                  } catch (failure) {
                    setError((failure as Error).message);
                  }
                }}
              >
                加入草稿
              </button>
            </div>
          ))}
          {page.cursor && (
            <button onClick={() => setCursor(page.cursor)}>下一页</button>
          )}
          {cursor && (
            <button onClick={() => setCursor(null)}>回到第一页</button>
          )}
          <p className="subtle">
            内容加入草稿后，保存栏目或组合才会正式保存。来源停用后仍保留已保存内容。
          </p>
        </div>
      )}
    </div>
  );
}
