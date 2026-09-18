import {
  CheckCircle2,
  CircleHelp,
  ContactRound,
  Image,
  Layers3,
  Sparkles,
} from "lucide-react";
import type { MappingReview, TemplateNode, TemplatePlan } from "./types";
import { targetLabel } from "./visual";
import { reviewProblems } from "./review";

/** 用资料和栏目摘要呈现 AI 结果；原始段落范围留到主动调整时展示 */
export default function RecognitionSummary({
  plan,
  nodes,
  review,
  onLocate,
  onRepair,
}: {
  plan: TemplatePlan;
  nodes: TemplateNode[];
  review: MappingReview | null;
  onLocate: (id: string) => void;
  onRepair: () => void;
}) {
  const personal = plan.fields.filter(
    /* 栏目标题单独显示且不混入个人资料 */ (field) =>
      field.target.startsWith("personal."),
  );
  const groups = new Map<string, typeof personal>();
  for (const field of personal)
    groups.set(field.target, [...(groups.get(field.target) ?? []), field]);
  const problems = reviewProblems(review);
  return (
    <div className="template-result-scroll">
      <div className="template-result-heading">
        {review?.ready ? <CheckCircle2 size={28} /> : <CircleHelp size={28} />}
        <div>
          <h3>
            {!review
              ? "正在检查识别结果"
              : review.ready
                ? "当前模板已准备好"
                : `还需处理 ${problems.length} 项问题`}
          </h3>
          <p>
            {!review
              ? "检查通过后将自动生成试填预览。"
              : review.ready
                ? "当前模板检查已通过，可查看试填效果，也可以随时调整。"
                : "以下问题解决后即可试填和保存，已识别的资料和栏目保留在下方。"}
          </p>
        </div>
      </div>
      {!!problems.length && (
        <section
          className="template-result-section template-questions"
          tabIndex={-1}
          aria-label="阻止试填和保存的问题"
        >
          <h3>暂时无法试填和保存的原因</h3>
          <div className="template-problem-list">
            {problems.map(
              /* 有位置的问题可直接调整；其余原因保持正常文字亮度 */ (
                problem,
                index,
              ) =>
                problem.nodes.length ? (
                  <button
                    key={index}
                    onClick={
                      /* 定位问题原文；进入试填旁的修正面板 */ () =>
                        onLocate(problem.nodes[0])
                    }
                  >
                    {problem.message} · 定位调整
                  </button>
                ) : (
                  <p key={index}>{problem.message}</p>
                ),
            )}
          </div>
          <button className="primary" onClick={onRepair}>
            <Sparkles size={16} /> AI 修复这些问题
          </button>
          <p>也可以在“Word 试填与调整”右侧选择对应内容来修正。</p>
        </section>
      )}
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
            /* 同类资料合并展示；点击后可核对具体替换位置 */ ([
              target,
              fields,
            ]) => (
              <button
                key={target}
                onClick={
                  /* 进入当前资料的人工调整 */ () => onLocate(fields[0].node)
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
                /* 照片可直接打开调整且不显示底层图片编号 */ () =>
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
            /* 栏目以用途和已识别字段呈现且不要求用户理解样本边界 */ (
              region,
              index,
            ) => (
              <button
                key={index}
                onClick={
                  /* 主动调整时定位可编辑样本 */ () =>
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
                          /* 展示字段中文名称 */ (field) =>
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
      {!nodes.length && <p className="subtle">正在读取模板内容…</p>}
    </div>
  );
}
