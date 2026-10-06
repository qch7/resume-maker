import {
  locateWindow,
  windowId,
} from "@resume-maker/plugin-sdk/plugins/window";

export interface WindowDetail {
  number?: number;
  title?: string;
  status?: string;
  connected?: boolean;
  last_seen?: number;
}

interface Props {
  ids: string[];
  details?: Record<string, WindowDetail>;
  busy: boolean;
  onRetain(id: string): void;
  onStatus(message: string): void;
}

/** 按页面名称和标签序号辨认窗口，断连时说明恢复副本的处理方式 */
export default function WaitingWindows(props: Props) {
  return props.ids.map((id, index) => {
    const detail = props.details?.[id];
    const current = id === windowId;
    const offline =
      !detail?.connected || Date.now() / 1000 - (detail.last_seen ?? 0) > 10;
    return (
      <div className="plugin-waiting-window" key={id}>
        <p>
          <strong>
            {current ? "当前窗口" : `窗口 ${detail?.number ?? index + 1}`} ·{" "}
            {detail?.title || "未记录页面名称的旧窗口"}
          </strong>
        </p>
        <p>{offline ? "已关闭或暂时离线" : "在线，正在等待草稿保存"}</p>
        {detail?.last_seen && (
          <p>
            最后响应：
            {new Date(detail.last_seen * 1000).toLocaleString("zh-CN")}
          </p>
        )}
        {offline ? (
          <>
            <p>
              若找不到该窗口，可保留它的恢复副本后继续切换；旧输入以后需核对恢复。
            </p>
            <button disabled={props.busy} onClick={() => props.onRetain(id)}>
              保留恢复副本并继续
            </button>
          </>
        ) : (
          <>
            {detail?.status && <p>{detail.status}</p>}
            <button
              disabled={props.busy}
              onClick={() => {
                const located = locateWindow(id);
                props.onStatus(
                  located
                    ? "已发送定位提示。若浏览器未自动切换，请查看标题带有“待保存”的标签页。"
                    : "浏览器不支持窗口定位，请按页面名称和窗口序号查找标签页。",
                );
              }}
            >
              {current ? "标记当前标签页" : "定位窗口"}
            </button>
          </>
        )}
      </div>
    );
  });
}
