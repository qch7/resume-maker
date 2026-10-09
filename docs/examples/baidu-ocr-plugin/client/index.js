import { createElement, useEffect, useState } from "/shared/react.js";

/** 注册独立设置页面，配置编辑使用宿主已有的插件管理表单 */
export function activate(context) {
  /** 展示本机配置状态，只有用户点击时才请求百度鉴权 */
  function BaiduSettings({ active, run }) {
    const [status, setStatus] = useState(null);
    const [message, setMessage] = useState("");
    const [busy, setBusy] = useState(false);
    useEffect(() => {
      if (!active) return;
      let current = true;
      context.request("status", null).then(
        (value) => {
          if (current) {
            setStatus(value);
            setMessage("");
          }
        },
        (error) => {
          if (current) setMessage(error.message);
        },
      );
      return () => {
        current = false;
      };
    }, [active]);

    /** 手动验证密钥，仅获取令牌，不发送图片或产生识别调用 */
    async function connect() {
      setBusy(true);
      setMessage("");
      try {
        await context.request("connect", null);
        setMessage("鉴权成功。识别接口权限和额度将在实际 OCR 时校验。");
      } catch (error) {
        setMessage(error.message);
      } finally {
        setBusy(false);
      }
    }

    return createElement(
      "section",
      { className: "baidu-ocr-settings" },
      createElement("h2", null, "百度云 OCR"),
      createElement(
        "p",
        null,
        "在设置 → 插件中搜索百度云 OCR，展开配置，填写凭据文件的绝对路径并应用变更。",
      ),
      createElement(
        "p",
        null,
        status
          ? "当前接口：" +
              status.api +
              (status.configured ? "，凭据已配置。" : "，尚未配置凭据。")
          : "正在读取配置状态。",
      ),
      createElement(
        "button",
        {
          disabled: busy || !status?.configured,
          onClick: () => run(connect),
        },
        busy ? "检查中…" : "检查百度鉴权",
      ),
      createElement("p", { role: "status" }, message),
      createElement(
        "p",
        null,
        "图片及扫描页会上传百度。请在插件管理中停用 RapidOCR，再启用本插件，并保留本地 OCR 统一入口。",
      ),
    );
  }
  context.settingsPage({
    id: context.id + "/settings",
    title: "百度 OCR",
    order: 90,
    component: BaiduSettings,
  });
}
