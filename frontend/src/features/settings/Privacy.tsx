import { useEffect, useState } from "react";
import { api } from "../../shared/lib/api";

interface RequestRecord {
  id: string;
  created_at: string;
  replacements: number;
  status: string;
  payload: unknown;
}

/** 管理本机敏感词并检查实际外发的脱敏请求 */
export default function Privacy() {
  const [terms, setTerms] = useState("");
  const [version, setVersion] = useState(0);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState("");
  const [records, setRecords] = useState<RequestRecord[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true;
    void api<{ terms: string[]; version: number }>("/privacy")
      .then((value) => {
        if (active) {
          setTerms(value.terms.join("\n"));
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
    <section>
      <h3>隐私保护 · 已开启</h3>
      <p className="subtle">
        每轮发送前替换已知个人信息和常见敏感格式，真实值只在本机还原。
        原始图片和扫描件不会发送；模板按文字结构识别，证书可手动录入。
      </p>
      <p className="subtle">
        自动检测可能遗漏未登记的姓名、单位或特殊格式，请补充敏感词。 AI 使用 API
        凭据，无法使用仅订阅登录的连接；不接入旧模型会话。
      </p>
      <label>
        补充敏感词（每行一个，如姓名、学校、单位、住址）
        <textarea
          rows={4}
          value={terms}
          disabled={!loaded || busy}
          onChange={(event) => setTerms(event.target.value)}
        />
      </label>
      <button
        disabled={!loaded || busy}
        onClick={() =>
          void perform(async () => {
            const saved = await api<{ version: number }>(
              "/privacy/terms",
              "PUT",
              {
                terms: terms.split("\n").filter((value) => value.trim()),
                version,
              },
            );
            setVersion(saved.version);
            setNotice("敏感词已保存，后续请求自动生效。");
          })
        }
      >
        保存敏感词
      </button>
      <details>
        <summary>本地检测一段文字</summary>
        <label>
          待检测文字
          <textarea
            rows={3}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <button
          disabled={busy || !loaded || !text}
          onClick={() =>
            void perform(async () => {
              const value = await api<{ text: string; replacements: number }>(
                "/privacy/preview",
                "POST",
                { text },
              );
              setPreview(value.text);
              setNotice(
                `已替换 ${value.replacements} 处内容，本次检测未发送给模型。`,
              );
            })
          }
        >
          仅在本机检测
        </button>
        {preview && (
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
            {preview}
          </pre>
        )}
      </details>
      <details>
        <summary>最近模型请求（最多 10 条）</summary>
        <p className="subtle">
          显示实际发送的请求体，不包含 API
          密钥或还原表。记录仍可能含业务内容，可随时清除。
        </p>
        <button
          disabled={busy}
          onClick={() =>
            void perform(async () => {
              setRecords(await api<RequestRecord[]>("/privacy/requests"));
            })
          }
        >
          刷新发送记录
        </button>
        <button
          disabled={busy}
          onClick={() =>
            void perform(async () => {
              await api("/privacy/requests", "DELETE");
              setRecords([]);
            })
          }
        >
          清除记录
        </button>
        {records.map((record) => (
          <details key={record.id}>
            <summary>
              {record.created_at} · 替换 {record.replacements} 处 ·{" "}
              {(
                {
                  prepared: "准备发送",
                  completed: "完成",
                  failed: "失败",
                  cancelled: "取消",
                } as Record<string, string>
              )[record.status] ?? record.status}
            </summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {JSON.stringify(record.payload, null, 2)}
            </pre>
          </details>
        ))}
      </details>
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
