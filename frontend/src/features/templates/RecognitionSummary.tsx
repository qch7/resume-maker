import {
  CheckCircle2,
  CircleHelp,
  ContactRound,
  Image,
  Layers3,
} from "lucide-react";
import type { MappingReview, TemplateNode, TemplatePlan } from "./types";
import { targetLabel } from "./visual";

/** 用资料和栏目摘要呈现 AI 结果，原始段落范围留到主动调整时展示。 */
export default function RecognitionSummary({
  plan,
  nodes,
  review,
  onLocate,
}: {
  plan: TemplatePlan;
  nodes: TemplateNode[];
  review: MappingReview | null;
  onLocate: (id: string) => void;
}) {
  const personal = plan.fields.filter(
    /* 栏目标题单独显示，不混入个人资料。 */ (field) =>
      field.target.startsWith("personal."),
  );
  const groups = new Map<string, typeof personal>();
  for (const field of personal)
    groups.set(field.target, [...(groups.get(field.target) ?? []), field]);
  const questions =
    (review?.issues?.length ?? review?.errors.length ?? 0) +
    (review?.missing?.length ?? 0);
  return (
    <div className="template-result-scroll">
      <div className="template-result-heading">
        {review?.ready ? <CheckCircle2 size={28} /> : <CircleHelp size={28} />}
        <div>
          <h3>{review?.ready ? "模板已准备好" : "识别结果"}</h3>
          <p>
            {review?.ready
              ? "自动检查已通过，可查看试填效果，也可以随时调整。"
              : "先查看已识别的资料和栏目，剩余疑问可交给 AI 继续完善。"}
          </p>
        </div>
      </div>
      <div className="template-result-stats">
        <span>
          <ContactRound size={19} />
          <strong>{groups.size}</strong> 类资料
        </span>
        <span>
          <Layers3 size={19} />
          <strong>{plan.repeats.length}</strong> 个栏目
        </span>
        <span>
          <Image size={19} />
          <strong>{plan.photos.length}</strong> 处照片
        </span>
      </div>
      <section className="template-result-section">
        <h3>个人资料</h3>
        <div className="template-field-cards">
          {[...groups].map(
            /* 同类资料合并展示，点击后可核对具体替换位置。 */ ([
              target,
              fields,
            ]) => (
              <button
                key={target}
                onClick={
                  /* 进入当前资料的人工调整。 */ () => onLocate(fields[0].node)
                }
              >
                <strong>{targetLabel(target)}</strong>
                <span>{fields[0].quote || "新增填写位置"}</span>
                <small>
                  {fields.length > 1
                    ? `${fields.length} 处同步替换`
                    : "已找到替换位置"}{" "}
                  · 调整
                </small>
              </button>
            ),
          )}
          {plan.photos.length > 0 && (
            <button
              onClick={
                /* 照片可直接打开调整，不显示底层图片编号。 */ () =>
                  onLocate(plan.photos[0])
              }
            >
              <strong>简历照片</strong>
              <span>使用个人信息中的照片</span>
              <small>调整照片位置</small>
            </button>
          )}
        </div>
        {!groups.size && (
          <p className="subtle">尚未找到个人资料位置，可让 AI 继续识别。</p>
        )}
      </section>
      <section className="template-result-section">
        <h3>经历和栏目</h3>
        <div className="template-section-cards">
          {plan.repeats.map(
            /* 栏目以用途和已识别字段呈现，不要求用户理解样本边界。 */ (
              region,
              index,
            ) => (
              <button
                key={index}
                onClick={
                  /* 主动调整时定位可编辑样本。 */ () =>
                    onLocate(region.sample_start)
                }
              >
                <Layers3 size={20} />
                <div>
                  <strong>
                    {region.section === "projects"
                      ? "项目经历"
                      : region.section}
                  </strong>
                  <span>
                    {[
                      ...new Set(
                        region.fields.map(
                          /* 展示字段中文名称。 */ (field) =>
                            targetLabel(field.target),
                        ),
                      ),
                    ].join(" · ")}
                  </span>
                  <small>按当前简历的条目自动增减</small>
                </div>
                <span>调整</span>
              </button>
            ),
          )}
        </div>
      </section>
      {review && !review.ready && (
        <section className="template-result-section template-questions">
          <h3>需要确认</h3>
          <p>
            {questions
              ? `${questions} 项映射或资料位置需要完善。`
              : "还有少量内容需要判断用途。"}
            先使用右侧的“AI 继续完善”，也可以点击问题自行调整。
          </p>
          {(
            review.issues ??
            review.errors.map(
              /* 没有定位信息的文档级问题仍显示说明。 */ (message) => ({
                message,
                nodes: [],
              }),
            )
          ).map(
            /* 每个错误只展示一次，点击定位相关内容。 */ (issue, index) => (
              <button
                key={index}
                disabled={!issue.nodes.length}
                onClick={
                  /* 定位问题涉及的样本或资料。 */ () =>
                    onLocate(issue.nodes[0])
                }
              >
                {issue.message}
              </button>
            ),
          )}
          {review.missing?.map(
            /* 资料名称转换成可读提示。 */ (target) => (
              <p key={target}>还需安排：{targetLabel(target)}</p>
            ),
          )}
          {!!review.unresolved.length && (
            <details>
              <summary>
                查看尚未归类的 {review.unresolved.length} 处原文
              </summary>
              {review.unresolved.map(
                /* 细节默认折叠，仍可逐项核对。 */ (node) => (
                  <button
                    key={node.id}
                    onClick={/* 定位未知原文。 */ () => onLocate(node.id)}
                  >
                    {node.kind === "image" ? "图片用途待确认" : node.text}
                  </button>
                ),
              )}
            </details>
          )}
        </section>
      )}
      {!nodes.length && <p className="subtle">正在读取模板内容…</p>}
    </div>
  );
}
