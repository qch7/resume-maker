"""只通过固定文件编号提供脱敏文字，不接受任意路径或可执行命令"""

import json
import re
import sys
from pathlib import Path

MAX_MESSAGE = 2 * 1024 * 1024
NAMES = re.compile(r"context\.txt|source-[0-9]{4}\.txt")
TOOLS = [
    {
        "name": "read_material",
        "description": "读取脱敏副本的一段文字，行号从 1 开始",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "line_count": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["file"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_materials",
        "description": "在脱敏副本中搜索普通文字，返回文件编号和行号",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def contents(root, name):
    """文件名、链接和大小同时校验，读取范围始终限定在当前材料目录"""
    if not isinstance(name, str) or not NAMES.fullmatch(name):
        raise ValueError("文件编号不在允许范围内")
    file = root / name
    if (
        file.is_symlink()
        or file.is_junction()
        or file.resolve().parent != root
        or file.stat().st_nlink != 1
        or file.stat().st_size > MAX_MESSAGE
    ):
        raise ValueError("材料文件不符合读取规则")
    return file.read_text(encoding="utf-8").splitlines()


def call(root, name, args):
    """限制搜索和读取的参数、次数及输出长度，不执行材料中的指令"""
    if name == "read_material":
        if set(args) - {"file", "start_line", "line_count"}:
            raise ValueError("读取参数不受支持")
        start, count = args.get("start_line", 1), args.get("line_count", 100)
        if type(start) is not int or type(count) is not int or start < 1 or not 1 <= count <= 200:
            raise ValueError("读取行数不在允许范围内")
        lines = contents(root, args.get("file"))
        value = [
            {"line": i + 1, "text": text}
            for i, text in enumerate(lines)
            if start <= i + 1 < start + count
        ]
    elif name == "search_materials":
        query = args.get("query")
        if set(args) != {"query"} or not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise ValueError("搜索参数不受支持")
        value = []
        for file in sorted(root.iterdir()):
            if not NAMES.fullmatch(file.name):
                continue
            for i, text in enumerate(contents(root, file.name)):
                if query.casefold() in text.casefold():
                    value.append({"file": file.name, "line": i + 1, "text": text[:1000]})
                    if len(value) == 100:
                        break
            if len(value) == 100:
                break
    else:
        raise ValueError("工具不在允许范围内")
    return json.dumps(value, ensure_ascii=False)[:24000]


def dispatch(root, request):
    """实现必要的 MCP 方法，所有未知方法均显式拒绝"""
    method = request.get("method")
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "resume-materials", "version": "1"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = request.get("params", {})
        try:
            text = call(root, params.get("name"), params.get("arguments", {}))
            return {"content": [{"type": "text", "text": text}]}
        except (OSError, ValueError, TypeError, AttributeError):
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": "读取被拒绝：只允许已登记的脱敏材料编号和有界文字查询。",
                    }
                ],
            }
    raise ValueError("不支持的方法")


def main():
    """使用标准输入输出提供本次任务的只读工具，断开管道即退出"""
    root = Path(sys.argv[1])
    if root.is_symlink() or root.absolute() != root.resolve() or not root.is_dir():
        raise SystemExit(1)
    for _ in range(500):
        line = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not line or len(line) > MAX_MESSAGE:
            return
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or "id" not in request:
                continue
            reply = {"jsonrpc": "2.0", "id": request["id"], "result": dispatch(root, request)}
        except (ValueError, TypeError, AttributeError):
            reply = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid request"},
            }
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
