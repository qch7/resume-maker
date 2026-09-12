import { ArrowUp, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ResizeHandle from "../../shared/components/ResizeHandle";
import { useElementSize } from "../../shared/hooks/useElementSize";
import { api } from "../../shared/lib/api";
import { registerDraft } from "../../shared/lib/draftRegistry";
import { clamp, DEFAULT_LAYOUT } from "../../shared/lib/layout";
import { loadLocal } from "../../shared/lib/storage";
import type {
  ConversationDetail,
  Job,
  ProjectDetail,
  Proposal,
} from "../../shared/types/index";
import JobProgress from "./JobProgress";
import ProposalCard from "./ProposalCard";

interface Props {
  inputHeight: number;
  onInputHeight: (value: number) => void;
  detail: ConversationDetail;
  project: ProjectDetail;
  activeJob?: Job;
  run: (work: () => Promise<void>) => void;
  onSend: (text: string, scope: string, kind?: string) => Promise<void>;
  onAdopt: (proposal: Proposal) => Promise<void>;
  onRefresh: () => void;
}

/** 展示独立会话历史，维护输入草稿、讨论范围和防重复发送状态。 */
export default function Chat(props: Props) {
  const { detail, project, run, activeJob } = props;
  const pane = useRef<HTMLDivElement>(null);
  const size = useElementSize(pane);
  const inputMin = size.width <= 440 ? 150 : 120;
  const inputMax = Math.max(inputMin, size.height - 88);
  const inputHeight = clamp(props.inputHeight, inputMin, inputMax);
  const conversation = detail.conversation;
  const key = `rm.chat.${conversation.id}`;
  const [input, setInput] = useState<string>(
    /* 仅在首次挂载时读取缓存或计算初始状态。 */ () =>
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
  /** 串行刷新最新输入，只有写入成功后才推进已保存值和草稿版本。 */
  function flush() {
    const promise = chain.current
      .catch(
        /* 当前调用方已负责显示失败；恢复异步链以允许后续重试。 */ () => {},
      )
      .then(
        /* 在异步操作成功后同步结果及相关状态。 */ async () => {
          const value = current.current;
          if (value === saved.current) return;
          await api(`/conversations/${conversation.id}`, "PATCH", {
            input_draft: value,
          });
          saved.current = value;
          if (value === current.current) localStorage.removeItem(key);
          if (alive.current) setDraftStatus("输入草稿已保存");
        },
      );
    chain.current = promise;
    return promise;
  }
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      alive.current = true;
      const unregister = registerDraft(key, flush);
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () => {
        alive.current = false;
        unregister();
        void flush().catch(
          /* 当前调用方已负责显示失败；恢复异步链以允许后续重试。 */ () => {},
        );
      };
      // 组件按会话标识重新挂载，未完成的写入始终保留原会话归属。
    },
    [conversation.id],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      const timer = setTimeout(
        /* 延迟执行保存或提示清理，减少频繁更新。 */ () =>
          void flush().catch(
            /* 保留可展示的失败原因，并避免已取消请求更新页面。 */ (error) =>
              setDraftStatus(error.message),
          ),
        450,
      );
      return /* 在组件卸载或依赖变化时释放本次注册的资源。 */ () =>
        clearTimeout(timer);
    },
    [input],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      setScope(conversation.scope);
    },
    [conversation.scope],
  );
  useEffect(
    /* 同步当前依赖对应的外部状态，并在需要时返回清理函数。 */ () => {
      setTitle(conversation.title);
    },
    [conversation.title],
  );
  const latest = detail.jobs.at(-1);
  const failed =
    latest && ["failed", "interrupted"].includes(latest.status)
      ? latest
      : undefined;
  /** 提交绑定经历版本和范围的消息，以唯一请求标识防止重复入队。 */
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
    <div className="chat" ref={pane}>
      <div className="chat-history">
        <div className="chat-title">
          <input
            className="conversation-title"
            aria-label="会话名称"
            value={title}
            onChange={
              /* 把控件的新值同步到对应编辑状态。 */ (e) =>
                setTitle(e.target.value)
            }
            onBlur={
              /* 处理 onBlur 回调，将变化同步到工作台状态。 */ () => {
                if (title.trim() && title !== conversation.title)
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                      await api(`/conversations/${conversation.id}`, "PATCH", {
                        title: title.trim(),
                      });
                      props.onRefresh();
                    },
                  );
              }
            }
            onKeyDown={
              /* 处理方向键与边界快捷键，提供无鼠标的尺寸调整。 */ (e) => {
                if (e.key === "Enter") e.currentTarget.blur();
              }
            }
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
          {detail.messages.map(
            /* 按稳定标识生成对应的列表条目。 */ (message) => (
              <div key={message.id} className={`message ${message.role}`}>
                <span className="message-role">
                  {message.role === "user"
                    ? "你"
                    : message.role === "system"
                      ? "会话记录"
                      : "Codex"}
                </span>
                <div className="message-content">
                  <Markdown remarkPlugins={[remarkGfm]}>
                    {message.text}
                  </Markdown>
                </div>
                {message.role === "assistant" &&
                  detail.proposals
                    .filter(
                      /* 保留满足当前范围或有效性条件的条目。 */ (p) =>
                        p.job_id === message.job_id,
                    )
                    .map(
                      /* 按稳定标识生成对应的列表条目。 */ (p) => (
                        <ProposalCard
                          key={p.id}
                          value={p}
                          run={run}
                          adopt={props.onAdopt}
                          refresh={props.onRefresh}
                        />
                      ),
                    )}
                {message.role === "assistant" &&
                  detail.jobs
                    .find(
                      /* 定位与当前标识或条件匹配的条目。 */ (j) =>
                        j.id === message.job_id,
                    )
                    ?.result?.questions?.map(
                      /* 按稳定标识生成对应的列表条目。 */ (q, i) => (
                        <p className="question" key={i}>
                          待确认：{q}
                        </p>
                      ),
                    )}
              </div>
            ),
          )}
          {activeJob && <JobProgress key={activeJob.id} job={activeJob} />}
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
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      run(
                        /* 在草稿刷新成功后执行当前业务操作。 */ () =>
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
                  onClick={
                    /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                      run(
                        /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                          await api(
                            `/conversations/${conversation.id}/rebuild`,
                            "POST",
                          );
                          props.onRefresh();
                        },
                      )
                  }
                >
                  重建模型上下文
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      <ResizeHandle
        className="chat-resize"
        label="调整聊天记录与输入区高度"
        axis="y"
        reverse
        value={inputHeight}
        min={inputMin}
        max={inputMax}
        onChange={props.onInputHeight}
        onReset={
          /* 恢复该区域的默认布局尺寸。 */ () =>
            props.onInputHeight(DEFAULT_LAYOUT.chatInput)
        }
      />
      <form
        className="chat-composer"
        style={{ height: inputHeight }}
        onSubmit={
          /* 处理 onSubmit 回调，将变化同步到工作台状态。 */ (e) => {
            e.preventDefault();
            run(send);
          }
        }
      >
        <textarea
          aria-label="会话消息"
          disabled={sending}
          placeholder="例如：这条再精简一点，突出我负责的部分。"
          rows={3}
          value={input}
          onChange={
            /* 把控件的新值同步到对应编辑状态。 */ (e) => {
              current.current = e.target.value;
              setInput(e.target.value);
              setDraftStatus("正在保存输入草稿");
              localStorage.setItem(key, JSON.stringify(e.target.value));
            }
          }
          onKeyDown={
            /* 处理方向键与边界快捷键，提供无鼠标的尺寸调整。 */ (e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                run(send);
              }
            }
          }
        />
        <div className="composer-footer">
          <label className="scope-label">
            <span>本轮讨论范围</span>
            <select
              value={scope}
              onChange={
                /* 把控件的新值同步到对应编辑状态。 */ (e) => {
                  const next = e.target.value;
                  setScope(next);
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                      await api(`/conversations/${conversation.id}`, "PATCH", {
                        scope: next,
                      });
                    },
                  );
                }
              }
            >
              <option value="all">整个项目经历</option>
              {project.working.content.highlights.map(
                /* 按稳定标识生成对应的列表条目。 */ (h) => (
                  <option key={h.id} value={`highlight:${h.id}`}>
                    {h.title || "新亮点"}
                  </option>
                ),
              )}
            </select>
          </label>
          <span className="subtle" title={draftStatus || "Ctrl + Enter 发送"}>
            {draftStatus || "Ctrl + Enter 发送"}
          </span>
          {activeJob ? (
            <button
              type="button"
              onClick={
                /* 响应当前操作按钮，执行对应业务动作。 */ () =>
                  run(
                    /* 在草稿刷新成功后执行当前业务操作。 */ async () => {
                      await api(`/jobs/${activeJob.id}/cancel`, "POST");
                      props.onRefresh();
                    },
                  )
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
