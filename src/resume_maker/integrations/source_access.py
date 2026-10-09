"""在受信任后端按需生成脱敏源码，映射和原始路径不交给 CLI"""

import json
import os
import re
import secrets
import threading
from collections import deque
from fnmatch import fnmatchcase
from itertools import chain
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from resume_maker.integrations.providers.base import Cancelled, ProviderError
from resume_maker.integrations.source_context import BINARY, source_paths
from resume_maker.integrations.sources import EXCLUDED, SECRET_FILE, evidence_file, linked

MAX_RESULT = 24000


class SourceAccess:
    """本轮来源和脱敏表共用生命周期，分页只限制单次工作量和返回量"""

    def __init__(self, sources, data_dir, redactor, cancelled, audit=None):
        """登记授权来源而不提前枚举或读取文件"""
        self.sources = [
            {**row, "path": str(Path(row["path"]).resolve(strict=True))} for row in sources
        ]
        self.roots = {}
        for row in self.sources:
            stat = Path(row["path"]).stat()
            self.roots[row["id"]] = (stat.st_dev, stat.st_ino)
        self.data_dir = Path(data_dir).resolve()
        self.redactor, self.cancelled, self.audit = redactor, cancelled, audit
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.directory = TemporaryDirectory(prefix="resume-private-sources-")
        self.cache, self.cursors = {}, {}

    def __enter__(self):
        """提供请求级资源作用域"""
        return self

    def __exit__(self, *args):
        """请求结束即废弃游标并清理本轮脱敏文件"""
        self.stopped.set()
        self.cursors.clear()
        self.directory.cleanup()

    def check(self):
        """取消和连接关闭后停止继续读取原件"""
        if self.cancelled.is_set() or self.stopped.is_set():
            raise Cancelled("源码读取已取消。")

    def resolve(self, source, path):
        """每次使用前复核来源、目录、凭据、链接和硬链接边界"""
        if not isinstance(source, str) or not isinstance(path, str):
            raise ValueError("来源和相对路径必须是文字")
        source, path = self.redactor.restore(source), self.redactor.restore(path)
        row = next((row for row in self.sources if row["id"] == source), None)
        if row is None:
            raise ValueError("来源不属于本轮授权范围")
        root = Path(row["path"])
        stat = root.stat()
        if (
            linked(root)
            or root.resolve(strict=True) != root
            or (stat.st_dev, stat.st_ino) != self.roots[source]
        ):
            raise ValueError("授权来源已经变化，请重新发起分析")
        relative = PurePosixPath(path.replace("\\", "/"))
        if (
            any(SECRET_FILE.search(part) for part in relative.parts)
            or any(part.lower() in EXCLUDED for part in relative.parts[:-1])
            or relative.suffix.lower() in BINARY
        ):
            raise ValueError("该文件不属于允许的源码材料")
        file, path = evidence_file(self.sources, source, path, self.data_dir)
        if file.stat().st_nlink != 1:
            raise ValueError("源码不能通过硬链接访问")
        return source, path, file

    def metadata(self, source, path):
        """固定来源编号保持稳定，相对文件名脱敏并保留可还原引用"""
        safe_path = self.redactor.text(path)
        if len(safe_path) > 2000:
            safe_path = self.redactor.token(path)
        return {"source": source, "path": safe_path}

    def entries(self, source, pattern):
        """交替遍历所选来源，任意数量的目录和文件均可通过游标继续访问"""
        selected = [row for row in self.sources if not source or row["id"] == source]
        if not selected:
            raise ValueError("来源不属于本轮授权范围")
        pending = deque(
            (row, source_paths(Path(row["path"]), self.data_dir, self.cancelled))
            for row in selected
        )
        while pending:
            self.check()
            row, iterator = pending.popleft()
            try:
                file = next(iterator)
            except StopIteration:
                continue
            pending.append((row, iterator))
            if file is None:
                yield None
                continue
            path = file.relative_to(row["path"]).as_posix()
            if not fnmatchcase(path, pattern):
                yield None
                continue
            try:
                self.resolve(row["id"], path)
            except (OSError, ValueError):
                yield None
                continue
            yield row["id"], path

    def prepared(self, source, path):
        """仅在文件被读取或搜索时脱敏，大小不作为拒绝条件"""
        self.check()
        source, path, file = self.resolve(source, path)
        before = file.stat()
        stamp = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        version = (len(self.redactor.values), len(self.redactor.secrets))
        cached = self.cache.get((source, path))
        if cached and cached[:2] == (stamp, version):
            return cached[2]
        descriptor = os.open(
            file, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if opened.st_nlink != 1 or (opened.st_dev, opened.st_ino) != stamp[:2]:
                raise ValueError("读取前文件已变化")
            chunks = []
            while chunk := stream.read(1024 * 1024):
                self.check()
                chunks.append(chunk)
        self.check()
        _, _, current = self.resolve(source, path)
        after = current.stat()
        if stamp != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("读取期间文件已变化")
        raw = b"".join(chunks)
        text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        if "\0" in text:
            raise ValueError("文件不是可读源码文字")
        self.redactor.learn(text)
        safe = self.redactor.text(text)
        self.check()
        destination = Path(self.directory.name) / f"{secrets.token_hex(12)}.txt"
        destination.write_text(safe, encoding="utf-8", newline="")
        if cached:
            cached[2].unlink(missing_ok=True)
        self.cache[(source, path)] = (
            stamp,
            (len(self.redactor.values), len(self.redactor.secrets)),
            destination,
        )
        return destination

    def listing(self, source, pattern):
        """逐个返回脱敏文件名，枚举过程不读取正文"""
        for entry in self.entries(source, pattern):
            yield self.metadata(*entry) if entry else None

    def searching(self, source, pattern, query):
        """遍历全部候选文件的脱敏正文，结果和未命中进度均可分页继续"""
        for entry in self.entries(source, pattern):
            if not entry:
                yield None
                continue
            try:
                file = self.prepared(*entry)
            except (OSError, UnicodeError, ValueError, ProviderError):
                self.check()
                yield {**self.metadata(*entry), "unavailable": "该文件无法提供可用的脱敏文字"}
                continue
            position, number = 0, 0
            while True:
                self.check()
                current = self.prepared(*entry)
                with current.open(encoding="utf-8", newline="") as stream:
                    if current != file:
                        for _ in range(number):
                            self.check()
                            stream.readline()
                        file = current
                    else:
                        stream.seek(position)
                    lines = [stream.readline() for _ in range(100)]
                    position = stream.tell()
                # 跨页不持有文件句柄，其他工具读取可安全更新 Windows 缓存
                for line in lines:
                    if not line:
                        break
                    self.check()
                    number += 1
                    safe_line = self.redactor.text(self.redactor.restore(line))
                    safe_query = self.redactor.text(self.redactor.restore(query))
                    match = re.search(re.escape(safe_query), safe_line, re.IGNORECASE)
                    if match:
                        start = max(0, match.start() - 120)
                        yield {
                            **self.metadata(*entry),
                            "line": number,
                            "column": start + 1,
                            "text": safe_line.rstrip("\r\n")[start : start + 1000],
                        }
                    else:
                        yield None
                if not lines[-1]:
                    break

    def page(self, name, args):
        """在响应或本次扫描工作量达到边界时保存继续位置，不截断全库范围"""
        allowed = {"source", "glob", "cursor"} | ({"query"} if name == "search_sources" else set())
        if set(args) - allowed:
            raise ValueError("分页参数不受支持")
        source, pattern, query = (
            args.get("source", ""),
            args.get("glob", "*"),
            args.get("query", ""),
        )
        if not all(isinstance(value, str) for value in (source, pattern, query)):
            raise ValueError("查询参数必须是文字")
        if len(pattern) > 2000 or (name == "search_sources" and not 1 <= len(query) <= 200):
            raise ValueError("查询参数超出单次上限")
        source, pattern = self.redactor.restore(source), self.redactor.restore(pattern)
        key = (name, source, pattern, query)
        cursor = args.get("cursor")
        if cursor is not None:
            if not isinstance(cursor, str) or cursor not in self.cursors:
                raise ValueError("游标不属于当前请求")
            saved_key, iterator = self.cursors.pop(cursor)
            if key != saved_key:
                self.cursors[cursor] = (saved_key, iterator)
                raise ValueError("继续查询时不能更改来源或条件")
        else:
            iterator = (
                self.searching(source, pattern, query) if query else self.listing(source, pattern)
            )
        rows, complete = [], False
        for _ in range(1000):
            self.check()
            try:
                row = next(iterator)
            except StopIteration:
                complete = True
                break
            if row is None:
                continue
            if len(json.dumps(rows + [row], ensure_ascii=False)) > MAX_RESULT - 200:
                iterator = chain([row], iterator)
                break
            rows.append(row)
            if len(rows) == 100:
                break
        next_cursor = None
        if not complete:
            next_cursor = secrets.token_hex(16)
            self.cursors[next_cursor] = (key, iterator)
        return {"results": rows, "next_cursor": next_cursor, "complete": complete}

    def read(self, args):
        """按原始行号读取脱敏文件，长行和输出上限均提供继续坐标"""
        if set(args) - {"source", "path", "start_line", "start_column", "line_count"}:
            raise ValueError("读取参数不受支持")
        start, column, count = (
            args.get("start_line", 1),
            args.get("start_column", 1),
            args.get("line_count", 100),
        )
        if (
            any(type(value) is not int or value < 1 for value in (start, column, count))
            or count > 200
        ):
            raise ValueError("读取范围不受支持")
        source, path, _ = self.resolve(args.get("source"), args.get("path"))
        file = self.prepared(source, path)
        result = {**self.metadata(source, path), "lines": [], "next": None, "eof": True}
        with file.open(encoding="utf-8", newline="") as stream:
            for number, line in enumerate(stream, 1):
                self.check()
                if number < start:
                    continue
                text = line.rstrip("\r\n")
                offset = column - 1 if number == start else 0
                if offset > len(text):
                    raise ValueError("读取列号超出当前行")
                row = {"line": number, "text": text[offset : offset + 2000]}
                if (
                    len(result["lines"]) == count
                    or len(
                        json.dumps({**result, "lines": [*result["lines"], row]}, ensure_ascii=False)
                    )
                    > MAX_RESULT - 200
                ):
                    result.update(
                        next={"start_line": number, "start_column": offset + 1}, eof=False
                    )
                    break
                result["lines"].append(row)
                if offset + len(row["text"]) < len(text):
                    result.update(
                        next={"start_line": number, "start_column": offset + len(row["text"]) + 1},
                        eof=False,
                    )
                    break
        return result

    def call(self, name, args):
        """串行使用本轮脱敏映射，所有结果先通过同一网关再返回模型"""
        with self.lock:
            self.check()
            if not isinstance(args, dict):
                raise ValueError("工具参数必须是对象")
            if name == "read_source":
                result = self.read(args)
            elif name in {"list_source_files", "search_sources"}:
                result = self.page(name, args)
            else:
                raise ValueError("工具不在允许范围内")
            self.check()
            if self.audit:
                self.audit(name, result, self.redactor.count)
            return result
