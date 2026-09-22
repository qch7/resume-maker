"""只通过固定文件编号提供脱敏文字，不接受任意路径或可执行命令"""

import http.client
import json
import re
import sys
from pathlib import Path

MAX_MESSAGE = 2 * 1024 * 1024
NAMES = re.compile(r"context\.txt|source-[0-9]{4}\.txt")
TOOLS = [
    {
        "name": "read_material",
        "description": "读取脱敏副本，行号和列号从 1 开始。返回 next_column 时，"
        "以该记录的 line 和 next_column 作为 start_line 和 start_column 继续读取；"
        "否则从最后返回行的下一行继续",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "start_column": {"type": "integer", "minimum": 1},
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

SOURCE_TOOLS = [
    {
        "name": "list_source_files",
        "description": "列出授权来源的文件名，不读取正文。"
        "source 留空表示所有来源，glob 匹配相对路径。"
        "结果 complete=false 时用 next_cursor 和相同条件继续，空 results 不表示结束。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "glob": {"type": "string"},
                "cursor": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_sources",
        "description": "在授权来源的脱敏源码中搜索普通文字，忽略大小写，"
        "可用 source 和 glob 缩小范围。"
        "全部文件均可继续搜索；complete=false 时以 next_cursor 和相同条件继续，即使本页没有命中。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "source": {"type": "string"},
                "glob": {"type": "string"},
                "cursor": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_source",
        "description": "按 source 编号和相对 path 读取脱敏源码，支持列出或搜索返回的脱敏路径。"
        "行号对应原件，列号对应脱敏行，均从 1 开始；有 next 时用其中坐标继续，文件大小不限制访问。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "start_column": {"type": "integer", "minimum": 1},
                "line_count": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["source", "path"],
            "additionalProperties": False,
        },
    },
]


def source_call(endpoint, name, arguments):
    """仅访问本轮本机网关，通道凭据不作为工具参数或结果返回"""
    if endpoint is None:
        raise ValueError("当前任务没有授权源码来源")
    connection = http.client.HTTPConnection("127.0.0.1", endpoint["port"], timeout=60)
    try:
        connection.request(
            "POST",
            "/materials",
            body=json.dumps({"name": name, "arguments": arguments}).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + endpoint["token"],
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        raw = response.read(MAX_MESSAGE + 1)
        if response.status != 200 or len(raw) > MAX_MESSAGE:
            raise ValueError("源码网关返回异常")
        value = json.loads(raw)
        if "error" in value:
            raise ValueError("源码读取被拒绝")
        return json.dumps(value["result"], ensure_ascii=False)
    except (OSError, http.client.HTTPException) as exc:
        raise ValueError("源码通道已关闭或读取被拒绝") from exc
    finally:
        connection.close()


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
        if set(args) - {"file", "start_line", "start_column", "line_count"}:
            raise ValueError("读取参数不受支持")
        start, count = args.get("start_line", 1), args.get("line_count", 100)
        column = args.get("start_column", 1)
        if (
            type(start) is not int
            or type(count) is not int
            or type(column) is not int
            or start < 1
            or column < 1
            or not 1 <= count <= 200
        ):
            raise ValueError("读取行数不在允许范围内")
        lines = contents(root, args.get("file"))
        value = []
        for index in range(start - 1, min(len(lines), start - 1 + count)):
            offset = column - 1 if index == start - 1 else 0
            text = lines[index]
            if offset > len(text):
                raise ValueError("读取列号超出当前行")
            row = {"line": index + 1, "text": text[offset : offset + 2000]}
            if offset + len(row["text"]) < len(text):
                row["next_column"] = offset + len(row["text"]) + 1
            value.append(row)
            if "next_column" in row:
                break
    elif name == "search_materials":
        query = args.get("query")
        if set(args) != {"query"} or not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise ValueError("搜索参数不受支持")
        value = []
        for file in sorted(root.iterdir()):
            if not NAMES.fullmatch(file.name):
                continue
            for i, text in enumerate(contents(root, file.name)):
                match = re.search(re.escape(query), text, re.IGNORECASE)
                if match:
                    offset = max(0, match.start() - 120)
                    value.append(
                        {
                            "file": file.name,
                            "line": i + 1,
                            "column": offset + 1,
                            "text": text[offset : offset + 1000],
                        }
                    )
                    if len(value) == 100:
                        break
            if len(value) == 100:
                break
    else:
        raise ValueError("工具不在允许范围内")
    rows, size = [], 2
    for row in value:
        encoded = json.dumps(row, ensure_ascii=False)
        extra = len(encoded) + (2 if rows else 0)
        if size + extra > 24000:
            break
        rows.append(encoded)
        size += extra
    return "[" + ", ".join(rows) + "]"


def dispatch(root, request, endpoint=None):
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
        return {"tools": TOOLS + (SOURCE_TOOLS if endpoint else [])}
    if method == "tools/call":
        params = request.get("params", {})
        try:
            name, arguments = params.get("name"), params.get("arguments", {})
            text = (
                source_call(endpoint, name, arguments)
                if name in {tool["name"] for tool in SOURCE_TOOLS}
                else call(root, name, arguments)
            )
            return {"content": [{"type": "text", "text": text}]}
        except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
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
    endpoint = None
    if len(sys.argv) == 3:
        config = Path(sys.argv[2])
        if (
            config.is_symlink()
            or config.resolve().parent != root.parent / "control"
            or config.stat().st_nlink != 1
        ):
            raise SystemExit(1)
        endpoint = json.loads(config.read_text(encoding="utf-8"))
    while True:
        line = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not line or len(line) > MAX_MESSAGE:
            return
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or "id" not in request:
                continue
            reply = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": dispatch(root, request, endpoint),
            }
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
