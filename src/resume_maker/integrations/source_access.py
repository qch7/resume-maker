"""在受信任后端按需生成脱敏源码，映射、原始路径不交给 CLI"""

import json
import os
import re
import secrets
import threading
from array import array
from collections import OrderedDict, deque
from fnmatch import fnmatchcase
from itertools import chain
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from resume_maker.integrations.source_context import BINARY, source_paths
from resume_maker.integrations.sources import EXCLUDED, SECRET_FILE, evidence_file, linked
from resume_maker.sdk.model import Cancelled, ProviderError

MAX_RESULT = 24000
MAX_SOURCE_FILE_BYTES = 32 * 1024 * 1024
MAX_SOURCE_CACHE_BYTES = 128 * 1024 * 1024
MAX_SOURCE_CACHE_ENTRIES = 256
MAX_SOURCE_CURSORS = 128
LINE_INDEX_STRIDE = 128


class SourceBudgetExceeded(ProviderError):
    """明确报告无法在本轮预算内提供的文件，不能把结果当成完整来源"""


class SourceRow(dict):
    """结果只序列化公开字段，本机位置用于规则换代后重新核验完整原文"""

    def __init__(self, value, entry, generation, *, line=None, query=None):
        """推迟发布的命中保留行号，不从已截取的片段恢复隐私原文"""
        super().__init__(value)
        self.entry, self.generation = entry, generation
        self.line, self.query = line, query


class SourceQuery:
    """同一搜索游标按规则代次复用查询表达式"""

    def __init__(self, value):
        """原始查询只在当前受信任任务中保存"""
        self.value, self.generation, self.pattern = value, None, None

    def prepare(self, redactor):
        """查询自身发现的凭据也先登记，再读取安全副本"""
        if self.generation != redactor.generation:
            safe = redactor.text(redactor.restore(self.value))
            self.pattern = re.compile(re.escape(safe), re.IGNORECASE)
            self.generation = redactor.generation
        return self.pattern


class SourceAccess:
    """本轮来源、脱敏表共用生命周期，分页只限制单次工作量、返回量"""

    def __init__(
        self,
        sources,
        data_dir,
        redactor,
        cancelled,
        audit=None,
        *,
        max_file_bytes=MAX_SOURCE_FILE_BYTES,
        max_cache_bytes=MAX_SOURCE_CACHE_BYTES,
    ):
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
        self.cache, self.cursors = OrderedDict(), OrderedDict()
        self.max_file_bytes, self.max_cache_bytes = max_file_bytes, max_cache_bytes

    def __enter__(self):
        """提供请求级资源作用域"""
        return self

    def __exit__(self, *args):
        """请求结束即废弃游标并清理本轮脱敏文件"""
        self.stopped.set()
        self.cursors.clear()
        self.cache.clear()
        self.directory.cleanup()

    def check(self):
        """取消、连接关闭后停止继续读取原件"""
        if self.cancelled.is_set() or self.stopped.is_set():
            raise Cancelled("源码读取已取消。")

    def resolve(self, source, path):
        """每次使用前复核来源、目录、凭据、链接、硬链接边界"""
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
        """交替遍历所选来源，任意数量的目录、文件均可通过游标继续访问"""
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
        """预先核验全文内存预算，安全副本按字节、数量淘汰"""
        self.check()
        source, path, file = self.resolve(source, path)
        before = file.stat()
        if before.st_size > self.max_file_bytes:
            raise SourceBudgetExceeded("源码全文超过本轮内存预算，请拆分大文件后继续分析。")
        stamp = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        version = self.redactor.generation
        cached = self.cache.get((source, path))
        if cached and cached[:2] == (stamp, version):
            self.cache.move_to_end((source, path))
            return cached[2]
        descriptor = os.open(
            file, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if opened.st_nlink != 1 or (opened.st_dev, opened.st_ino) != stamp[:2]:
                raise ValueError("读取前文件已变化")
            raw = bytearray()
            while chunk := stream.read(1024 * 1024):
                self.check()
                if len(raw) + len(chunk) > self.max_file_bytes:
                    raise SourceBudgetExceeded("源码在读取时超过本轮内存预算，请拆分后继续分析。")
                raw.extend(chunk)
        self.check()
        _, _, current = self.resolve(source, path)
        after = current.stat()
        if stamp != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("读取期间文件已变化")
        text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        if "\0" in text:
            raise ValueError("文件不是可读源码文字")
        self.redactor.learn(text)
        safe = self.redactor.text(text)
        self.check()
        encoded = safe.encode("utf-8")
        size = len(encoded)
        if size > self.max_cache_bytes:
            raise SourceBudgetExceeded("脱敏源码超过本轮缓存预算，请拆分大文件后继续分析。")
        if cached:
            self.cache.pop((source, path))
            cached[2].unlink(missing_ok=True)
        while self.cache and (
            len(self.cache) >= MAX_SOURCE_CACHE_ENTRIES
            or sum(row[4] for row in self.cache.values()) + size > self.max_cache_bytes
        ):
            _, evicted = self.cache.popitem(last=False)
            evicted[2].unlink(missing_ok=True)
        destination = Path(self.directory.name) / f"{secrets.token_hex(12)}.txt"
        offsets = array("Q", [0])
        for number, match in enumerate(re.finditer(rb"\r\n|\r|\n", encoded), 1):
            if number % LINE_INDEX_STRIDE == 0:
                self.check()
                offsets.append(match.end())
        destination.write_bytes(encoded)
        self.cache[(source, path)] = (
            stamp,
            self.redactor.generation,
            destination,
            offsets,
            size,
        )
        return destination

    def seek_line(self, stream, entry, line):
        """定位到最近的稀疏索引，索引随同代次安全副本一起刷新或淘汰"""
        offsets = self.cache[entry][3]
        index = min((line - 1) // LINE_INDEX_STRIDE, len(offsets) - 1)
        stream.seek(offsets[index])
        return index * LINE_INDEX_STRIDE + 1

    def listing(self, source, pattern):
        """逐个返回脱敏文件名，枚举过程不读取正文"""
        for entry in self.entries(source, pattern):
            yield self.source_row(self.metadata(*entry), entry) if entry else None

    def source_row(self, value, entry, *, line=None, query=None):
        """记录当前结果的隐私代次，内部定位信息不进入 JSON"""
        return SourceRow(value, entry, self.redactor.generation, line=line, query=query)

    def match_row(self, line, number, entry, query, metadata):
        """仅在完整安全副本中匹配，跨行保护不会因逐行还原而消失"""
        match = query.pattern.search(line)
        if match is None:
            return None
        start = max(0, match.start() - 120)
        return self.source_row(
            {
                **metadata,
                "line": number,
                "column": start + 1,
                "text": line.rstrip("\r\n")[start : start + 1000],
            },
            entry,
            line=number,
            query=query,
        )

    def refresh_row(self, row):
        """刷新推迟发布的旧代次结果，完整文件负责跨行身份识别"""
        if not isinstance(row, SourceRow) or row.generation == self.redactor.generation:
            return row
        metadata = self.metadata(*row.entry)
        if row.line is None:
            return self.source_row({**row, **metadata}, row.entry)
        row.query.prepare(self.redactor)
        try:
            file = self.prepared(*row.entry)
            row.query.prepare(self.redactor)
            metadata = self.metadata(*row.entry)
            with file.open(encoding="utf-8", newline="") as stream:
                first = self.seek_line(stream, row.entry, row.line)
                for _ in range(first, row.line):
                    self.check()
                    stream.readline()
                self.check()
                return self.match_row(stream.readline(), row.line, row.entry, row.query, metadata)
        except SourceBudgetExceeded as exc:
            return self.source_row({**metadata, "unavailable": str(exc)}, row.entry)
        except (OSError, UnicodeError, ValueError, ProviderError):
            self.check()
            return self.source_row(
                {**metadata, "unavailable": "该文件无法提供可用的脱敏文字"}, row.entry
            )

    def refresh_rows(self, rows):
        """同页后读文件发现新身份时，先前收集的命中也必须使用最新完整副本"""
        for _ in range(3):
            generation = self.redactor.generation
            rows = [updated for row in rows if (updated := self.refresh_row(row)) is not None]
            if self.redactor.generation == generation:
                return rows
        raise ProviderError("读取期间隐私规则持续变化，请重新搜索。")

    def searching(self, source, pattern, query):
        """遍历全部候选文件的脱敏正文，结果、未命中进度均可分页继续"""
        query = SourceQuery(query)
        query.prepare(self.redactor)
        for entry in self.entries(source, pattern):
            if not entry:
                yield None
                continue
            try:
                self.metadata(*entry)
                file = self.prepared(*entry)
            except SourceBudgetExceeded as exc:
                yield self.source_row({**self.metadata(*entry), "unavailable": str(exc)}, entry)
                continue
            except (OSError, UnicodeError, ValueError, ProviderError):
                self.check()
                yield self.source_row(
                    {**self.metadata(*entry), "unavailable": "该文件无法提供可用的脱敏文字"}, entry
                )
                continue
            position, number = 0, 0
            while True:
                self.check()
                query.prepare(self.redactor)
                metadata = self.metadata(*entry)
                current = self.prepared(*entry)
                query.prepare(self.redactor)
                metadata = self.metadata(*entry)
                generation = self.redactor.generation
                with current.open(encoding="utf-8", newline="") as stream:
                    if current != file:
                        first = self.seek_line(stream, entry, number + 1)
                        for _ in range(first, number + 1):
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
                    if (
                        generation != self.redactor.generation
                        or (cached := self.cache.get(entry)) is None
                        or cached[2] != file
                    ):
                        # 预读批次在其他工具发现身份或淘汰副本后，从尚未发布的行重新定位
                        break
                    number += 1
                    yield self.match_row(line, number, entry, query, metadata)
                else:
                    continue
                if not line:
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
        rows, complete, size = [], False, 2
        for _ in range(1000):
            self.check()
            try:
                row = next(iterator)
            except StopIteration:
                complete = True
                break
            if row is None:
                continue
            row = self.refresh_row(row)
            if row is None:
                continue
            extra = len(json.dumps(row, ensure_ascii=False)) + (2 if rows else 0)
            if size + extra > MAX_RESULT - 200:
                iterator = chain([row], iterator)
                break
            rows.append(row)
            size += extra
            if len(rows) == 100:
                break
        if any(
            isinstance(row, SourceRow) and row.generation != self.redactor.generation
            for row in rows
        ):
            refreshed, rows, size = self.refresh_rows(rows), [], 2
            for index, row in enumerate(refreshed):
                extra = len(json.dumps(row, ensure_ascii=False)) + (2 if rows else 0)
                if size + extra > MAX_RESULT - 200:
                    iterator = chain(refreshed[index:], iterator)
                    complete = False
                    break
                rows.append(row)
                size += extra
        next_cursor = None
        if not complete:
            while len(self.cursors) >= MAX_SOURCE_CURSORS:
                _, (_key, expired) = self.cursors.popitem(last=False)
                close = getattr(expired, "close", None)
                if close:
                    close()
            next_cursor = secrets.token_hex(16)
            self.cursors[next_cursor] = (key, iterator)
        return {"results": rows, "next_cursor": next_cursor, "complete": complete}

    def read(self, args):
        """按原始行号读取脱敏文件，长行、输出上限均提供继续坐标"""
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
        # 路径可能首次登记凭据，必须先处理路径再准备正文
        self.metadata(source, path)
        file = self.prepared(source, path)
        result = {**self.metadata(source, path), "lines": [], "next": None, "eof": True}
        size = len(json.dumps(result, ensure_ascii=False))
        with file.open(encoding="utf-8", newline="") as stream:
            first = self.seek_line(stream, (source, path), start)
            for number, line in enumerate(stream, first):
                # 跳过已有安全副本时按小批次检查，实际返回前仍核验最新隐私代次
                if number >= start or number % 128 == 1:
                    self.check()
                if number < start:
                    continue
                text = line.rstrip("\r\n")
                offset = column - 1 if number == start else 0
                if offset > len(text):
                    raise ValueError("读取列号超出当前行")
                row = {"line": number, "text": text[offset : offset + 2000]}
                extra = len(json.dumps(row, ensure_ascii=False)) + (2 if result["lines"] else 0)
                if len(result["lines"]) == count or size + extra > MAX_RESULT - 200:
                    result.update(
                        next={"start_line": number, "start_column": offset + 1}, eof=False
                    )
                    break
                result["lines"].append(row)
                size += extra
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
