import { createElement, useEffect, useState } from "/shared/react.js";

/** 每个客户端实例拥有自己的页面和 RPC 身份 */
export function activate(context) {
  /** 编辑当前实例的笔记，错误保留在页面上 */
  function Notes() {
    const [text, setText] = useState("");
    const [message, setMessage] = useState("");
    useEffect(() => {
      let active = true;
      context.request("read", null).then(
        (value) => {
          if (active) setText(value);
        },
        (error) => {
          if (active) setMessage(error.message);
        },
      );
      return () => {
        active = false;
      };
    }, []);
    return createElement(
      "section",
      null,
      createElement("h2", null, context.config.title),
      createElement("textarea", {
        value: text,
        maxLength: 2000,
        onChange: (event) => setText(event.target.value),
      }),
      createElement(
        "button",
        {
          onClick: () =>
            context.request("save", text).then(
              () => setMessage("已保存"),
              (error) => setMessage(error.message),
            ),
        },
        "保存笔记",
      ),
      createElement("p", { role: "status" }, message),
    );
  }
  context.page({
    id: "community.notes/main",
    title: String(context.config.title),
    order: 100,
    component: Notes,
  });
}
