import { FolderPlus } from "lucide-react";
import { useState } from "react";
import { api } from "../../shared/lib/api";
import PathInput from "../../shared/components/PathInput";
import type { SettingsPanelProps } from "../../plugins/contracts";

/** 来源插件独立持有扫描候选，未启用时不加载扫描流程 */
export default function SourceSettings(props: SettingsPanelProps) {
  const [root, setRoot] = useState("");
  const [candidates, setCandidates] = useState<
    { name: string; roots: string[]; selected: boolean }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  /** 将扫描和导入串行提交到工作台统一错误处理 */
  function run(work: () => Promise<void>) {
    props.run(async () => {
      setBusy(true);
      setNotice("");
      try {
        await work();
      } finally {
        setBusy(false);
      }
    });
  }
  return (
    <>
      <p className="subtle">
        扫描项目集合后确认归组。关联多个代码目录的项目会同时建立可独立勾选和对话的子项目。
      </p>
      <PathInput
        label="项目集合目录"
        kind="folder"
        placeholder="D:\...\Projects"
        value={root}
        onChange={setRoot}
        disabled={busy}
      />
      <button
        disabled={busy || !root.trim()}
        onClick={() =>
          run(async () => {
            const value = await api<{ name: string; roots: string[] }[]>(
              "/projects/scan",
              "POST",
              { path: root },
            );
            setCandidates(
              value.map((p) => ({
                ...p,
                selected: true,
              })),
            );
          })
        }
      >
        扫描目录
      </button>
      {candidates.length > 0 && (
        <>
          <div className="candidates">
            {candidates.map((p, index) => (
              <label className="candidate" key={index}>
                <input
                  type="checkbox"
                  checked={p.selected}
                  onChange={(e) =>
                    setCandidates((values) =>
                      values.map((v, i) =>
                        i === index ? { ...v, selected: e.target.checked } : v,
                      ),
                    )
                  }
                />
                <div>
                  <strong>{p.name}</strong>
                  <span>{p.roots.length} 个来源</span>
                  {p.roots.map((path) => (
                    <code key={path}>{path}</code>
                  ))}
                </div>
              </label>
            ))}
          </div>
          <button
            className="primary"
            disabled={busy || !candidates.some((p) => p.selected)}
            onClick={() =>
              run(async () => {
                for (const p of candidates.filter((p) => p.selected))
                  await api("/projects", "POST", {
                    name: p.name,
                    roots: p.roots,
                  });
                await props.onChanged();
                setNotice("选中的项目已导入，已有项目会保留原记录。");
                setCandidates([]);
              })
            }
          >
            <FolderPlus size={16} />
            导入选中项目
          </button>
        </>
      )}
      {notice && <p role="status">{notice}</p>}
    </>
  );
}
