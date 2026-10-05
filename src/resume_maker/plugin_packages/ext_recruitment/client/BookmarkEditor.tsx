import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import Dialog from "./Dialog";
import type { Bookmark, Domain } from "./model";

/** 编辑一个收藏及其多个入口，失败时保留表单内容 */
export default function BookmarkEditor({
  initial,
  domains,
  categories,
  onSave,
  onClose,
  onRefresh,
}: {
  initial: Bookmark;
  domains: Domain[];
  categories: Domain[];
  onSave: (item: Bookmark) => Promise<void>;
  onClose: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [value, setValue] = useState(() => structuredClone(initial));
  const [tags, setTags] = useState(initial.tags.join("，"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [discard, setDiscard] = useState(false);
  /** 关闭前保留仍在编辑的内容，由用户选择是否放弃 */
  function close() {
    if (
      JSON.stringify(value) !== JSON.stringify(initial) ||
      tags !== initial.tags.join("，")
    )
      setDiscard(true);
    else onClose();
  }
  /** 校验表单后等待本机保存，成功才关闭窗口 */
  async function save() {
    setBusy(true);
    setError("");
    try {
      await onSave({
        ...value,
        name: value.name.trim(),
        tags: [
          ...new Set(
            tags
              .split(/[,，;；\n]/)
              .map((tag) => tag.trim())
              .filter(Boolean),
          ),
        ],
      });
      onClose();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** 获取其他窗口的最新列表，保留本表单供用户核对后再次保存 */
  async function refresh() {
    setBusy(true);
    try {
      await onRefresh();
      setError("已刷新列表。本次编辑内容已保留，再次保存将采用以上内容。");
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={initial.name ? "编辑收藏" : "添加收藏"}
      busy={busy}
      onClose={close}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <fieldset disabled={busy} className="recruitment-fields">
          <label>
            企业或网站名称
            <input
              autoFocus
              required
              maxLength={100}
              value={value.name}
              placeholder="例如：腾讯、我的目标公司"
              onChange={(e) => setValue({ ...value, name: e.target.value })}
            />
          </label>
          <div className="form-grid">
            <label>
              领域
              <select
                value={value.domain_id}
                onChange={(e) =>
                  setValue({ ...value, domain_id: e.target.value })
                }
              >
                <option value="">无领域</option>
                {domains.map((domain) => (
                  <option key={domain.id} value={domain.id}>
                    {domain.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              分类
              <select
                value={value.category}
                onChange={(e) =>
                  setValue({ ...value, category: e.target.value })
                }
              >
                <option value="">无分类</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            简介
            <input
              value={value.description}
              maxLength={2000}
              placeholder="简介"
              onChange={(e) =>
                setValue({ ...value, description: e.target.value })
              }
            />
          </label>
          <label>
            业务标签
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="逗号分隔"
            />
          </label>
          <div className="section-heading">
            <h3>招聘网址</h3>
            <button
              type="button"
              disabled={value.links.length >= 30}
              onClick={() =>
                setValue({
                  ...value,
                  links: [...value.links, { label: "", url: "" }],
                })
              }
            >
              <Plus size={14} />
              添加链接
            </button>
          </div>
          {value.links.map((link, index) => (
            <div className="recruitment-link-edit" key={index}>
              <input
                required
                aria-label={`链接 ${index + 1} 名称`}
                placeholder="校招 / 社招 / 企业官网"
                maxLength={100}
                value={link.label}
                onChange={(e) =>
                  setValue({
                    ...value,
                    links: value.links.map((item, i) =>
                      i === index ? { ...item, label: e.target.value } : item,
                    ),
                  })
                }
              />
              <input
                required
                type="url"
                pattern="https?://.*"
                maxLength={4096}
                aria-label={`链接 ${index + 1} 网址`}
                placeholder="https://"
                value={link.url}
                onChange={(e) =>
                  setValue({
                    ...value,
                    links: value.links.map((item, i) =>
                      i === index ? { ...item, url: e.target.value } : item,
                    ),
                  })
                }
              />
              <button
                type="button"
                className="icon-button"
                aria-label={`删除链接 ${index + 1}`}
                disabled={value.links.length === 1}
                onClick={() =>
                  setValue({
                    ...value,
                    links: value.links.filter((_, i) => i !== index),
                  })
                }
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
          <label>
            个人备注
            <textarea
              rows={3}
              maxLength={10000}
              value={value.notes}
              placeholder="备注"
              onChange={(e) => setValue({ ...value, notes: e.target.value })}
            />
          </label>
          <label className="recruitment-checkbox">
            <input
              type="checkbox"
              checked={value.favorite}
              onChange={(e) =>
                setValue({ ...value, favorite: e.target.checked })
              }
            />
            星标
          </label>
        </fieldset>
        {error && (
          <div className="recruitment-error" role="alert">
            {error}
            <button
              type="button"
              disabled={busy}
              onClick={() => void refresh()}
            >
              刷新列表，保留输入
            </button>
          </div>
        )}
        {discard ? (
          <footer>
            <span>放弃本次未保存的修改？</span>
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
              {busy ? "正在保存…" : "保存收藏"}
            </button>
          </footer>
        )}
      </form>
    </Dialog>
  );
}
