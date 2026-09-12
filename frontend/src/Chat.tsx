import { useEffect, useRef, useState } from "react";
import { ArrowUp, RotateCcw, Square } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, loadLocal, request } from "./api";
import { registerDraft } from "./drafts";
import type {
  ConversationDetail,
  Experience,
  Highlight,
  Job,
  ProjectDetail,
  Proposal,
} from "./types";

interface Props {
  detail: ConversationDetail;
  project: ProjectDetail;
  activeJob?: Job;
  run: (work: () => Promise<void>) => void;
  onSend: (text: string, scope: string, kind?: string) => Promise<void>;
  onAdopt: (proposal: Proposal) => Promise<void>;
  onRefresh: () => void;
}

export function ExperiencePreview({ value }: { value: Experience }) {
  return (
    <div className="experience-preview">
      <strong>{value.title}</strong>
      <span className="subtle">
        {value.period} {value.role}
      </span>
      <p>
        <b>技术栈：</b>
        {value.stack.join("、")}
      </p>
      <p>{value.description}</p>
      {value.highlights.map((h) => (
        <p key={h.id}>
          <b>{h.title}：</b>
          {h.text}
        </p>
      ))}
    </div>
  );
}

function ProposalCard({
  value,
  run,
  adopt,
  refresh,
}: {
  value: Proposal;
  run: Props["run"];
  adopt: Props["onAdopt"];
  refresh: Props["onRefresh"];
}) {
  return (
    <article className="proposal">
      <div className="section-heading">
        <strong>
          {value.target === "experience" ? "整段经历建议" : "亮点修改建议"}
        </strong>
        <span className="tag">
          {(
            {
              pending: "待采用",
              adopted: "已放入草稿",
              rejected: "已拒绝",
            } as Record<string, string>
          )[value.status] ?? value.status}
        </span>
      </div>
      <p className="subtle">{value.reason}</p>
      {value.target === "experience" ? (
        <>
          <details>
            <summary>查看修改前的整段经历</summary>
            <ExperiencePreview value={value.before as Experience} />
          </details>
          <ExperiencePreview value={value.after as Experience} />
        </>
      ) : (
        <div className="diff">
          <div>
            <span className="subtle">原文</span>
            <p>
              <b>{(value.before as Highlight)?.title}：</b>
              {(value.before as Highlight)?.text}
            </p>
          </div>
          <div>
            <span className="subtle">建议</span>
            <p>
              <b>{(value.after as Highlight).title}：</b>
              {(value.after as Highlight).text}
            </p>
          </div>
        </div>
      )}
      {value.status === "pending" && (
        <div className="actions">
          <button className="primary" onClick={() => run(() => adopt(value))}>
            采用到草稿
          </button>
          <button
            onClick={() =>
              run(async () => {
                await api(`/proposals/${value.id}/reject`, "POST");
                refresh();
              })
            }
          >
            拒绝
          </button>
        </div>
      )}
    </article>
  );
}

function Progress({ job }: { job: Job }) {
  const [events, setEvents] = useState<
    {
      kind: string;
      data: {
        text?: string;
        type?: string;
        input_tokens?: number;
        output_tokens?: number;
      };
    }[]
  >([]);
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await request(`/jobs/${job.id}/events`, {
          signal: controller.signal,
        });
        const reader = response.body!.getReader(),
          decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() ?? "";
          for (const chunk of chunks) {
            if (chunk.includes("event: done")) continue;
            const data = chunk
              .split("\n")
              .find((line) => line.startsWith("data: "));
            if (data) {
              const event = JSON.parse(data.slice(6));
              setEvents((previous) => [...previous.slice(-19), event]);
            }
          }
        }
      } catch (error) {
        if (!controller.signal.aborted)
          setEvents((previous) => [
            ...previous,
            { kind: "error", data: { text: (error as Error).message } },
          ]);
      }
    })();
    return () => controller.abort();
  }, [job.id]);
  const last = [...events].reverse().find((e) => e.data.text);
  return (
    <div className="job-progress">
      <div className="row">
        <span className="pulse" />
        <span>
          {job.status === "queued"
            ? "任务排队中"
            : (last?.data.text ?? "正在连接 Codex")}
        </span>
      </div>
      <details>
        <summary>查看执行过程</summary>
        {events.map((event, index) => (
          <div className="activity" key={index}>
            {event.data.text ??
              (event.kind === "usage"
                ? `输入 ${event.data.input_tokens ?? "未知"} / 输出 ${event.data.output_tokens ?? "未知"} token`
                : event.kind === "thread"
                  ? "会话已连接"
                  : (event.data.type ?? event.kind))}
          </div>
        ))}
      </details>
    </div>
  );
}

export default function Chat(props: Props) {
  const { detail, project, run, activeJob } = props;
  const conversation = detail.conversation;
  const key = `rm.chat.${conversation.id}`;
  const [input, setInput] = useState<string>(() =>
    loadLocal(key, conversation.input_draft),
  );
  const [scope, setScope] = useState(conversation.scope);
  const [title, setTitle] = useState(conversation.title);
  const [draftStatus, setDraftStatus] = useState("");
  const current = useRef(input),
    saved = useRef(conversation.input_draft),
    chain = useRef(Promise.resolve());
  const alive = useRef(true);
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);
  function flush() {
    const promise = chain.current
      .catch(() => {})
      .then(async () => {
        const value = current.current;
        if (value === saved.current) return;
        await api(`/conversations/${conversation.id}`, "PATCH", {
          input_draft: value,
        });
        saved.current = value;
        if (value === current.current) localStorage.removeItem(key);
        if (alive.current) setDraftStatus("输入草稿已保存");
      });
    chain.current = promise;
    return promise;
  }
  useEffect(() => {
    alive.current = true;
    const unregister = registerDraft(key, flush);
    return () => {
      alive.current = false;
      unregister();
      void flush().catch(() => {});
    };
    // The component is keyed by conversation; pending writes retain that conversation ID.
  }, [conversation.id]);
  useEffect(() => {
    const timer = setTimeout(
      () => void flush().catch((error) => setDraftStatus(error.message)),
      450,
    );
    return () => clearTimeout(timer);
  }, [input]);
  useEffect(() => {
    setScope(conversation.scope);
  }, [conversation.scope]);
  useEffect(() => {
    setTitle(conversation.title);
  }, [conversation.title]);
  const latest = detail.jobs.at(-1);
  const failed =
    latest && ["failed", "interrupted"].includes(latest.status)
      ? latest
      : undefined;
  async function send() {
    const value = current.current.trim();
    if (!value || activeJob || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    try {
      await flush();
      await props.onSend(value, scope);
      current.current = "";
      saved.current = "";
      setInput("");
      setDraftStatus("");
      localStorage.removeItem(key);
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }
  return (
    <div className="chat">
      <div className="chat-title">
        <input
          className="conversation-title"
          aria-label="会话名称"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => {
            if (title.trim() && title !== conversation.title)
              run(async () => {
                await api(`/conversations/${conversation.id}`, "PATCH", {
                  title: title.trim(),
                });
                props.onRefresh();
              });
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
          }}
        />
        <span className="subtle">{project.project.name} 的独立会话</span>
      </div>
      <div className="messages" aria-live="polite">
        {!detail.messages.length && (
          <div className="empty">
            <h3>从这段经历开始聊</h3>
            <p>分析项目源码，或讨论个人贡献、技术方案与具体亮点。</p>
          </div>
        )}
        {detail.messages.map((message) => (
          <div key={message.id} className={`message ${message.role}`}>
            <span className="message-role">
              {message.role === "user"
                ? "你"
                : message.role === "system"
                  ? "会话记录"
                  : "Codex"}
            </span>
            <div className="message-content">
              <Markdown remarkPlugins={[remarkGfm]}>{message.text}</Markdown>
            </div>
            {message.role === "assistant" &&
              detail.proposals
                .filter((p) => p.job_id === message.job_id)
                .map((p) => (
                  <ProposalCard
                    key={p.id}
                    value={p}
                    run={run}
                    adopt={props.onAdopt}
                    refresh={props.onRefresh}
                  />
                ))}
            {message.role === "assistant" &&
              detail.jobs
                .find((j) => j.id === message.job_id)
                ?.result?.questions?.map((q, i) => (
                  <p className="question" key={i}>
                    待确认：{q}
                  </p>
                ))}
          </div>
        ))}
        {activeJob && <Progress key={activeJob.id} job={activeJob} />}
        {failed && !activeJob && (
          <div className="error-panel">
            <strong>
              {failed.status === "interrupted"
                ? "上次任务被中断"
                : "任务未完成"}
            </strong>
            <p>{failed.error}</p>
            <div className="actions">
              <button
                onClick={() =>
                  run(() =>
                    props.onSend(
                      failed.request?.text ?? "继续上一轮请求",
                      failed.request?.scope ?? "all",
                      failed.kind,
                    ),
                  )
                }
              >
                <RotateCcw size={14} />
                重试
              </button>
              <button
                onClick={() =>
                  run(async () => {
                    await api(
                      `/conversations/${conversation.id}/rebuild`,
                      "POST",
                    );
                    props.onRefresh();
                  })
                }
              >
                重建模型上下文
              </button>
            </div>
          </div>
        )}
      </div>
      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault();
          run(send);
        }}
      >
        <label className="scope-label">
          本轮讨论范围
          <select
            value={scope}
            onChange={(e) => {
              const next = e.target.value;
              setScope(next);
              run(async () => {
                await api(`/conversations/${conversation.id}`, "PATCH", {
                  scope: next,
                });
              });
            }}
          >
            <option value="all">整个项目经历</option>
            {project.working.content.highlights.map((h) => (
              <option key={h.id} value={`highlight:${h.id}`}>
                {h.title || "新亮点"}
              </option>
            ))}
          </select>
        </label>
        <textarea
          aria-label="会话消息"
          disabled={sending}
          placeholder="例如：这条再精简一点，突出我负责的部分。"
          rows={3}
          value={input}
          onChange={(e) => {
            current.current = e.target.value;
            setInput(e.target.value);
            setDraftStatus("正在保存输入草稿");
            localStorage.setItem(key, JSON.stringify(e.target.value));
          }}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
              e.preventDefault();
              run(send);
            }
          }}
        />
        <div className="composer-footer">
          <span className="subtle">{draftStatus || "Ctrl + Enter 发送"}</span>
          {activeJob ? (
            <button
              type="button"
              onClick={() =>
                run(async () => {
                  await api(`/jobs/${activeJob.id}/cancel`, "POST");
                  props.onRefresh();
                })
              }
            >
              <Square size={14} />
              停止
            </button>
          ) : (
            <button
              className="primary"
              type="submit"
              disabled={sending || !input.trim()}
            >
              <ArrowUp size={16} />
              发送
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
