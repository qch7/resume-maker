"""扩展资料的纯文本降级表示，不执行缺失插件的代码"""

from copy import deepcopy


def display_document(document):
    """展开明确的默认展示，缺少展示契约时阻止无提示丢失内容"""
    result = deepcopy(document)
    for owner, value in document.get("extensions", {}).items():
        display = value.get("display") if isinstance(value, dict) else None
        if not isinstance(display, dict):
            raise ValueError(f"扩展 {owner} 缺少可导出的默认展示，请启用对应插件处理。")
        if display.get("hidden") is True:
            continue
        title, text = display.get("title"), display.get("text")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 100
            or not isinstance(text, str)
            or len(text) > 10000
        ):
            raise ValueError(f"扩展 {owner} 的默认展示格式无效。")
        result["sections"].append(
            {
                "id": f"extension:{owner}",
                "title": title,
                "kind": "text",
                "visible": True,
                "entries": [{"id": "content", "details": text}],
            }
        )
    return result
