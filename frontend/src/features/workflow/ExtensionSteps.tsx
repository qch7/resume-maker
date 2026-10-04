import { useState } from "react";
import type { WorkflowInput } from "../../plugins/slots";
import { clientExtensions } from "../../plugins/extensions";
import { runPluginCommand } from "../../plugins/commands";

/** 额外制作步骤通过公开状态贡献和命令显示，单项失败不影响内置流程 */
export default function ExtensionSteps({ input }: { input: WorkflowInput }) {
  const steps = clientExtensions.workflow(input);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  if (!steps.length) return null;
  return (
    <div aria-label="扩展制作步骤">
      {steps.map((item) => (
        <div key={item.id}>
          <strong>
            {item.value.title}
            {item.status.done ? " · 已就绪" : ""}
          </strong>
          <p>{item.status.text}</p>
          <button
            disabled={!item.available || !!busy}
            onClick={() => {
              setError("");
              setBusy(item.id);
              void runPluginCommand(item.value.command)
                .catch(() =>
                  setError("步骤操作失败，请检查对应插件状态后重试。"),
                )
                .finally(() => setBusy(""));
            }}
          >
            打开{item.value.title}
          </button>
        </div>
      ))}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
