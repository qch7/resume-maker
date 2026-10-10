import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import Dialog from "./Dialog";
import type { BookmarkFile } from "./model";

/** 维护用户领域或分类，移除分组时迁移收藏或清除归属 */
export default function GroupsEditor({
  initial,
  kind,
  onSave,
  onClose,
}: {
  initial: BookmarkFile;
  kind: "domains" | "categories";
  onSave: (data: BookmarkFile) => Promise<void>;
  onClose: () => void;
}) {
  const [data, setData] = useState(() => structuredClone(initial));
  const [target, setTarget] = useState("");
  const label = kind === "domains" ? "领域" : "分类";
  const field = kind === "domains" ? "domain_id" : "category";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [discard, setDiscard] = useState(false);
  /** 将分组中的收藏迁移到目标分组或解除归属，保存后生效 */
  function remove(id: string) {
    if (target === id) {
      setError("请选择其他迁移目标。");
      return;
    }
    setError("");
    setData({
      ...data,
      [kind]: data[kind].filter((item) => item.id !== id),
      bookmarks: data.bookmarks.map((item) =>
        item[field] === id ? { ...item, [field]: target } : item,
      ),
    });
  }
  /** 提交领域名称和迁移后的收藏，校验失败保留当前副本 */
  async function save() {
    setBusy(true);
    setError("");
    try {
      await onSave(data);
      onClose();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 有未保存改动时先显示放弃入口 */
  function close() {
    if (JSON.stringify(data) !== JSON.stringify(initial)) setDiscard(true);
    else onClose();
  }
  return (
    <Dialog title={`管理${label}`} busy={busy} onClose={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <fieldset disabled={busy} className="recruitment-fields">
          {data[kind].map((domain) => (
            <div className="row" key={domain.id}>
              <input
                className="grow"
                required
                aria-label={`${label}名称 ${domain.name}`}
                maxLength={100}
                value={domain.name}
                onChange={(e) =>
                  setData({
                    ...data,
                    [kind]: data[kind].map((item) =>
                      item.id === domain.id
                        ? { ...item, name: e.target.value }
                        : item,
                    ),
                  })
                }
              />
              <span className="subtle">
                {
                  data.bookmarks.filter((item) => item[field] === domain.id)
                    .length
                }{" "}
                条
              </span>
              <button
                type="button"
                className="icon-button"
                aria-label={`删除${label} ${domain.name}`}
                onClick={() => remove(domain.id)}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          <button
            type="button"
            disabled={data[kind].length >= 100}
            onClick={() =>
              setData({
                ...data,
                [kind]: [
                  ...data[kind],
                  { id: crypto.randomUUID(), name: `新${label}` },
                ],
              })
            }
          >
            <Plus size={15} />
            添加{label}
          </button>
          <label>
            删除后移至
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">不分组</option>
              {data[kind].map((domain) => (
                <option key={domain.id} value={domain.id}>
                  {domain.name}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
        {error && (
          <p className="recruitment-error" role="alert">
            {error}
          </p>
        )}
        {discard ? (
          <footer>
            <span>放弃本次修改？</span>
            <button type="button" onClick={() => setDiscard(false)}>
              继续编辑
            </button>
            <button type="button" onClick={onClose}>
              放弃修改
            </button>
          </footer>
        ) : (
          <footer>
            <button type="button" disabled={busy} onClick={close}>
              取消
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "保存中…" : "保存"}
            </button>
          </footer>
        )}
      </form>
    </Dialog>
  );
}
