import { api } from "../../shared/lib/api";
import type { Experience, Highlight, Proposal } from "../../shared/types/index";

/** 以只读形式展示 AI 提议的完整经历；供采用前核对 */
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

/** 展示修改前后内容与建议原因；提供采用或拒绝入口 */
export default function ProposalCard({
  value,
  run,
  adopt,
  refresh,
}: {
  value: Proposal;
  run: (work: () => Promise<void>) => void;
  adopt: (proposal: Proposal) => Promise<void>;
  refresh: () => void;
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
