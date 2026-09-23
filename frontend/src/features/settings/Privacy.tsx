import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../shared/lib/api";

interface RequestRecord {
  id: string;
  created_at: string;
  replacements: number;
  status: string;
  payload: unknown;
}

interface PrivacyTerms {
  terms: string[];
  version: number;
}

/** 管理本机敏感词并检查交给模型的脱敏材料 */
export default function Privacy() {
  const [terms, setTerms] = useState("");
  const [savedTerms, setSavedTerms] = useState("");
  const [version, setVersion] = useState(0);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<{
    text: string;
    replacements: number;
  } | null>(null);
  const [records, setRecords] = useState<RequestRecord[]>([]);
  const [recordsLoaded, setRecordsLoaded] = useState(false);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const dirty = terms !== savedTerms;
  useEffect(() => {
    let active = true;
    void api<PrivacyTerms>("/privacy")
      .then((value) => {
        if (active) {
          setTerms(value.terms.join("\n"));
          setSavedTerms(value.terms.join("\n"));
          setVersion(value.version);
          setLoaded(true);
        }
      })
      .catch((error) => {
        if (active) setNotice(error.message);
      });
    return () => {
      active = false;
    };
  }, []);
  /** 串行执行本地操作并显示可处理的错误 */
  async function perform(work: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await work();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="privacy-settings" aria-label="隐私设置">
      <div className="privacy-status">
        <ShieldCheck size={18} />
        <strong>发送前脱敏</strong>
        <span>已开启</span>
        <small>原图留在本机 · 结果本机还原</small>
      </div>
      <div className="privacy-grid">
        <section className="privacy-card">
          <div className="section-heading">
            <h3>补充敏感词</h3>
            <small className="subtle">{dirty ? "未保存" : "每行一个"}</small>
          </div>
          <textarea
            aria-label="补充敏感词"
            rows={5}
            placeholder={"填写需要额外隐藏的内容\n如姓名、学校、单位"}
            value={terms}
            disabled={!loaded || busy}
            onChange={(event) => {
              setTerms(event.target.value);
              setPreview(null);
              setNotice("");
            }}
          />
          <div className="actions">
            <button
              className="primary"
              disabled={!loaded || busy || !dirty}
              onClick={() =>
                void perform(async () => {
                  const saved = await api<PrivacyTerms>(
                    "/privacy/terms",
                    "PUT",
                    {
                      terms: terms.split("\n").filter((value) => value.trim()),
                      version,
                    },
                  );
                  setVersion(saved.version);
                  setTerms(saved.terms.join("\n"));
                  setSavedTerms(saved.terms.join("\n"));
                  setPreview(null);
                  setNotice("敏感词已保存");
                })
              }
            >
              保存敏感词
            </button>
          </div>
        </section>
        <section className="privacy-card">
          <div className="section-heading">
            <h3>脱敏预览</h3>
            <small className="subtle">仅本机检测</small>
          </div>
          <textarea
            aria-label="待检测文字"
            rows={5}
            maxLength={30000}
            placeholder="粘贴文字，检查替换效果"
            value={text}
            disabled={busy}
            onChange={(event) => {
              setText(event.target.value);
              setPreview(null);
            }}
          />
          <div className="actions">
            <button
              disabled={busy || !loaded || !text.trim() || dirty}
              onClick={() =>
                void perform(async () => {
                  setPreview(
                    await api<{ text: string; replacements: number }>(
                      "/privacy/preview",
                      "POST",
                      { text },
                    ),
                  );
                })
              }
            >
              检测文字
            </button>
            {dirty && <small className="subtle">先保存敏感词</small>}
          </div>
        </section>
      </div>
      {preview && (
        <section className="privacy-result" aria-label="脱敏结果">
          <h3>已替换 {preview.replacements} 处</h3>
          <pre>{preview.text}</pre>
        </section>
      )}
      {notice && (
        <p className="privacy-notice" role="status">
          {notice}
        </p>
      )}
      <details className="privacy-disclosure">
        <summary>
          最近发送记录 <span>最多 10 条</span>
        </summary>
        <div className="actions">
          <button
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                setRecords(await api<RequestRecord[]>("/privacy/requests"));
                setRecordsLoaded(true);
              })
            }
          >
            {recordsLoaded ? "刷新记录" : "查看记录"}
          </button>
          <button
            disabled={busy || !recordsLoaded || !records.length}
            onClick={() =>
              void perform(async () => {
                await api("/privacy/requests", "DELETE");
                setRecords([]);
                setNotice("发送记录已清除");
              })
            }
          >
            清除记录
          </button>
          <small className="subtle">脱敏材料，可能含业务内容</small>
        </div>
        {recordsLoaded && !records.length && (
          <p className="subtle">暂无发送记录</p>
        )}
        {records.map((record) => (
          <details className="privacy-record" key={record.id}>
            <summary>
              <time dateTime={record.created_at}>
                {new Date(record.created_at).toLocaleString()}
              </time>
              <span>替换 {record.replacements} 处</span>
              <span>
                {(
                  {
                    prepared: "准备发送",
                    completed: "完成",
                    failed: "失败",
                    cancelled: "取消",
                  } as Record<string, string>
                )[record.status] ?? record.status}
              </span>
            </summary>
            <pre>{JSON.stringify(record.payload, null, 2)}</pre>
          </details>
        ))}
      </details>
      <details className="privacy-disclosure privacy-rules">
        <summary>自动处理范围</summary>
        <dl>
          <dt>自动隐藏</dt>
          <dd>姓名、联系方式、地址、学校、颁发单位、身份和证书编号等。</dd>
          <dt>正常保留</dt>
          <dd>
            证书和项目名称、专业、求职意向、成绩；命中敏感词或身份格式时仍隐藏。
          </dd>
          <dt>本机处理</dt>
          <dd>
            原图先提取文字；模板内嵌图片打上马赛克后供 AI 判断用途。
            低置信度文字整体隐藏，凭据直接移除。
          </dd>
          <dt>需要核对</dt>
          <dd>
            自动识别可能遗漏，特殊身份信息请补充敏感词。发送记录保留初始材料和最近工具结果。
          </dd>
        </dl>
      </details>
    </section>
  );
}
