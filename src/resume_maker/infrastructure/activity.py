"""独立保存可检索的本机活动，日志写入失败不影响业务事务"""

import json
import re
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from resume_maker.infrastructure.database import dump, now

SECRET_KEY = re.compile(
    r"authorization|cookie|password|passwd|secret|api[-_]?key|access[-_]?token|"
    r"refresh[-_]?token|id[-_]?token|x-resume-token|^token$|credential",
    re.I,
)
SECRET_TEXT = re.compile(
    r"(?i)(bearer\s+)[^\s\"'<>]+|"
    r"((?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|password|"
    r"authorization|x-resume-token|secret|\btoken)\s*[\"']?\s*[:=]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|(?:Bearer\s+)?[^\s\"',;}&]+)|"
    r"\bsk-[a-zA-Z0-9_-]{8,}|"
    r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"
)
MAX_DETAIL = 262_144
DEFAULT_POLLING_PATHS = "/api/state\n/api/honors\n/api/templates/analyses/*/progress"
SUMMARY_COLUMNS = (
    "id,created_at,category,level,source,event,title,trace_id,span_id,parent_span_id,"
    "job_id,conversation_id,project_id,duration_ms"
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
 id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
 category TEXT NOT NULL, level TEXT NOT NULL, source TEXT NOT NULL,
 event TEXT NOT NULL, title TEXT NOT NULL, trace_id TEXT NOT NULL DEFAULT '',
 span_id TEXT NOT NULL DEFAULT '', parent_span_id TEXT NOT NULL DEFAULT '',
 job_id TEXT NOT NULL DEFAULT '', conversation_id TEXT NOT NULL DEFAULT '',
 project_id TEXT NOT NULL DEFAULT '', duration_ms REAL, payload_json TEXT NOT NULL,
 origin_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS activity_filter ON activity(category, id);
CREATE INDEX IF NOT EXISTS activity_trace ON activity(trace_id, id);
CREATE INDEX IF NOT EXISTS activity_job ON activity(job_id, id);
CREATE INDEX IF NOT EXISTS activity_time ON activity(created_at);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def wildcard_pattern(value):
    """仅将星号转换成 SQL 通配符，其余字符保持字面含义"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("*", "%")


def safe_text(value):
    """遮盖文本中的常见鉴权值和私钥，保留调试需要的业务正文"""
    text = SECRET_TEXT.sub(lambda match: (match[1] or match[2] or "") + "[已遮盖]", value)
    return re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[已遮盖]@", text)


def safe_value(value, depth=0):
    """将领域对象变成有界 JSON，二进制只记录大小且未知对象不展开内部属性"""
    if depth > 16:
        return "[嵌套过深，已截断]"
    if isinstance(value, str):
        text = safe_text(value)
        return text if len(text) <= MAX_DETAIL else text[:MAX_DETAIL] + "\n[内容已截断]"
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"binary_bytes": len(value)}
    if isinstance(value, Path):
        return safe_text(str(value))
    if not isinstance(value, type) and hasattr(value, "model_dump"):
        return safe_value(value.model_dump(), depth + 1)
    if isinstance(value, dict):
        result = {
            safe_text(str(key)): "[已遮盖]"
            if SECRET_KEY.search(str(key))
            else safe_value(item, depth + 1)
            for key, item in list(value.items())[:1000]
        }
        if len(value) > 1000:
            result["_truncated_items"] = len(value) - 1000
        return result
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [safe_value(item, depth + 1) for item in items[:1000]]
        if len(items) > 1000:
            result.append({"_truncated_items": len(items) - 1000})
        return result
    return f"<{type(value).__name__}>"


def detail_json(value):
    """限制单条详情尺寸并明确标记截断，避免大响应无限占用日志空间"""
    encoded = dump(safe_value(value))
    if len(encoded) > MAX_DETAIL:
        return dump(
            {"_truncated": True, "original_chars": len(encoded), "preview": encoded[:MAX_DETAIL]}
        )
    return encoded


def mask_secrets(value, secrets):
    """遮盖已知凭据时仅修改 JSON 字符串，避免数字或布尔值损坏结构"""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[已遮盖]")
        return value
    if isinstance(value, list):
        return [mask_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: mask_secrets(item, secrets) for key, item in value.items()}
    return value


class ActivityLog:
    """每个应用实例独立持有日志库和保留策略"""

    def __init__(self, path: Path, *, max_records=50_000, retention_days=30, secrets=()):
        """建立独立日志库以保留现有业务数据库结构和用户数据"""
        self.path = path
        self.max_records, self.retention_days = max_records, retention_days
        self.lock = threading.Lock()
        self.secrets = {value for value in secrets if value}
        self.write_failures = 0
        self.last_error = ""
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            # 移除旧轮询合并的派生索引，原始日志和游标保持不变
            conn.execute("DROP TABLE IF EXISTS activity_responses")
            self._remember_cursor(conn, self._cursor(conn))
            self._prune(conn)
            conn.commit()

    def connect(self, *, check_same_thread=True):
        """创建短连接，日志锁和业务事务互不共享"""
        conn = sqlite3.connect(self.path, timeout=2, check_same_thread=check_same_thread)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _prune(self, conn):
        """清理超龄及超量记录，自动递增游标始终不会复用"""
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
        conn.execute("DELETE FROM activity WHERE created_at < ?", (cutoff,))
        conn.execute(
            "DELETE FROM activity WHERE id <= "
            "(SELECT id FROM activity ORDER BY id DESC LIMIT 1 OFFSET ?)",
            (self.max_records,),
        )

    def _cursor(self, conn):
        """同时读取保留记录和持久游标，清空日志后编号继续递增"""
        return conn.execute(
            "SELECT MAX(COALESCE((SELECT MAX(id) FROM activity),0),"
            "COALESCE((SELECT CAST(value AS INTEGER) FROM metadata WHERE key='last_id'),0))"
        ).fetchone()[0]

    def _remember_cursor(self, conn, identifier):
        """在写入或删除事务内保存日志游标，避免其他页面漏收新事件"""
        conn.execute(
            "INSERT INTO metadata(key,value) VALUES ('last_id',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(identifier),),
        )

    def write(self, category, event, title, payload=None, **fields) -> bool:
        """持久化脱敏事件并返回成功状态，失败计数供界面提示"""
        try:
            values = {
                "created_at": fields.pop("created_at", None),
                "category": category,
                "level": fields.pop("level", "info"),
                "source": fields.pop("source", "system"),
                "event": event,
                "title": safe_text(str(title))[:500],
                "payload_json": detail_json(payload),
                **fields,
            }
            with self.lock, closing(self.connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                values["id"] = self._cursor(conn) + 1
                values["created_at"] = values["created_at"] or now()
                if self.secrets:
                    values["title"] = mask_secrets(values["title"], self.secrets)
                    values["payload_json"] = dump(
                        mask_secrets(json.loads(values["payload_json"]), self.secrets)
                    )
                columns = ",".join(values)
                cursor = conn.execute(
                    f"INSERT OR IGNORE INTO activity({columns}) "
                    f"VALUES ({','.join('?' for _ in values)})",
                    tuple(values.values()),
                )
                if cursor.rowcount:
                    self._remember_cursor(conn, values["id"])
                    if values["id"] % min(100, self.max_records) == 0:
                        self._prune(conn)
                conn.commit()
            return True
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            self.write_failures += 1
            self.last_error = safe_text(str(exc))[:500]
            return False

    def filters(
        self,
        *,
        category="",
        level="",
        q="",
        trace_id="",
        job_id="",
        conversation_id="",
        since="",
        until="",
        hide_polling=False,
        hide_maintenance=False,
        hidden_rules=None,
        **_,
    ):
        """组合固定列的参数化条件，关键词按字面搜索全部正文和关联标识"""
        clauses, args = [], []
        service_patterns = []
        if hidden_rules is not None and hide_polling:
            service_patterns = [
                wildcard_pattern(rule.strip())
                for rule in dict.fromkeys(hidden_rules.splitlines())
                if rule.strip() and "/" not in rule and ":" not in rule
            ]
        elif hidden_rules is None and hide_maintenance:
            service_patterns = [wildcard_pattern("template_library.purge_expired")]
        if service_patterns and not trace_id:
            matches = " OR ".join("source LIKE ? ESCAPE '\\'" for _ in service_patterns)
            clauses.append(
                "NOT (category='service' AND level='info' AND event IN ('started','completed') "
                "AND COALESCE(duration_ms,0)<1000 "
                f"AND (({matches}) OR "
                "(source='template_library.state' AND parent_span_id IN "
                "(SELECT span_id FROM activity WHERE category='service' "
                "AND source='template_library.purge_expired' AND span_id<>'' "
                f"AND ({matches})))))"
            )
            args.extend(service_patterns * 2)
        if hidden_rules is not None and hide_polling and not trace_id:
            for rule in dict.fromkeys(hidden_rules.splitlines()):
                if ":" in rule and "/" not in rule:
                    kind, event = rule.strip().split(":", 1)
                    clauses.append(
                        "NOT (level='info' AND category=? AND event LIKE ? ESCAPE '\\' "
                        "AND COALESCE(duration_ms,0)<1000)"
                    )
                    args.extend((kind, wildcard_pattern(event)))
        if hide_polling and not trace_id:
            event_filter = (
                "((category='api' OR "
                "(category='service' AND event IN ('started','completed'))) "
                "AND COALESCE(duration_ms,0)<1000)"
                if hidden_rules is not None
                else "category IN ('api','service')"
            )
            clauses.append(
                f"NOT ({event_filter} AND level='info' "
                "AND trace_id IN (SELECT trace_id FROM hidden_polling))"
            )
            if hidden_rules is not None:
                clauses.append("id NOT IN (SELECT id FROM polling_request_starts)")
        for key, value in {"category": category, "level": level}.items():
            selected = list(
                dict.fromkeys(item.strip() for item in value.split(",") if item.strip())
            )
            if selected:
                clauses.append(f"{key} IN ({','.join('?' for _ in selected)})")
                args.extend(selected)
        for key, value in {
            "trace_id": trace_id,
            "job_id": job_id,
            "conversation_id": conversation_id,
        }.items():
            if value:
                clauses.append(f"{key}=?")
                args.append(value)
        for operator, value in ((">=", since), ("<=", until)):
            if value:
                clauses.append(f"created_at {operator} ?")
                args.append(value)
        if q:
            pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.append(
                "("
                + " OR ".join(
                    f"{key} LIKE ? ESCAPE '\\'"
                    for key in (
                        "title",
                        "payload_json",
                        "source",
                        "trace_id",
                        "job_id",
                        "conversation_id",
                    )
                )
                + ")"
            )
            args.extend([pattern] * 6)
        return " AND ".join(clauses) or "1=1", args

    def polling_cte(
        self,
        *,
        hide_polling=False,
        polling_paths=DEFAULT_POLLING_PATHS,
        hidden_rules=None,
        **_,
    ):
        """从成功响应识别轮询链路，路径只支持星号且其余字符按字面匹配"""
        patterns = []
        if hide_polling:
            if hidden_rules is not None:
                polling_paths = hidden_rules
            for path in dict.fromkeys(polling_paths.splitlines()):
                path = path.strip()
                match = re.fullmatch(
                    r"(?:(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) )?(/api/[^\s?#]*)", path
                )
                if match:
                    patterns.append(
                        (match[1] or "GET") + " " + wildcard_pattern(match[2]) + " · 200"
                    )
        matches = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in patterns) or "0"
        cte = (
            "WITH hidden_polling AS (SELECT trace_id,MAX(id) AS completed_id FROM activity "
            "WHERE category='api' AND event='response' AND level='info' AND trace_id<>'' "
            f"AND ({matches}) "
            "AND COALESCE(json_extract(payload_json,'$.error'),'') IN ('',0,'[]','{}') "
            "AND COALESCE(json_extract(payload_json,'$.response.body.errors'),'') "
            "IN ('',0,'[]','{}') GROUP BY trace_id) "
        )
        args = list(patterns)
        if hidden_rules is None:
            return cte, args
        endpoints = [pattern.removesuffix(" · 200") for pattern in patterns]
        starts = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in endpoints) or "0"
        cte += (
            ", polling_request_starts AS (SELECT id FROM activity WHERE category='api' "
            "AND event='request' AND level='info' AND COALESCE(duration_ms,0)<1000 "
            f"AND ({starts})) "
        )
        args.extend(endpoints)
        return cte, args

    def page(self, *, after=None, before=0, limit=200, **filters):
        """返回稳定游标分页，初次读取最近记录，增量读取保持顺序且不漏页"""
        where, args = self.filters(**filters)
        cte, polling_args = self.polling_cte(**filters)
        with closing(self.connect()) as conn:
            conn.execute("BEGIN")
            snapshot = self._cursor(conn)
            bounds, values = "id<=?", [snapshot]
            if after is not None:
                bounds += " AND id>?"
                values.append(after)
            if before:
                bounds += " AND id<?"
                values.append(before)
            direction = "ASC" if after is not None else "DESC"
            rows = conn.execute(
                cte + f"SELECT {SUMMARY_COLUMNS} FROM activity WHERE {where} AND {bounds} "
                f"ORDER BY id {direction} LIMIT ?",
                (*polling_args, *args, *values, limit + 1),
            ).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            if after is None:
                rows = rows[::-1]
            counts = dict(
                conn.execute(
                    cte + f"SELECT category,COUNT(*) FROM activity WHERE {where} "
                    "AND id<=? GROUP BY category",
                    (*polling_args, *args, snapshot),
                ).fetchall()
            )
            cursor = rows[-1]["id"] if after is not None and more else snapshot
            hidden = []
            if after is not None and filters.get("hide_polling") and not filters.get("trace_id"):
                hidden = [
                    row[0]
                    for row in conn.execute(
                        cte + "SELECT trace_id FROM hidden_polling WHERE completed_id>? "
                        "AND completed_id<=?",
                        (*polling_args, after, cursor),
                    )
                ]
        return {
            "events": [dict(row) for row in rows],
            "cursor": cursor,
            "hidden_trace_ids": hidden,
            "has_more": more,
            "oldest": rows[0]["id"] if rows else 0,
            "counts": counts,
            "total": sum(counts.values()),
            "write_failures": self.write_failures,
            "last_error": self.last_error,
            "retention_days": self.retention_days,
            "max_records": self.max_records,
        }

    def delete(self, *, before):
        """串行删除指定时间之前或全部日志，保留历史补录标记和递增游标"""
        with self.lock, closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._remember_cursor(conn, self._cursor(conn))
            cursor = conn.execute(
                "DELETE FROM activity" + (" WHERE created_at < ?" if before is not None else ""),
                (before,) if before is not None else (),
            )
            deleted = cursor.rowcount
            conn.execute("INSERT OR REPLACE INTO metadata VALUES ('history_imported','1')")
            conn.commit()
        return deleted

    def detail(self, identifier):
        """按需读取单条完整详情，列表轮询不反复传输大型正文"""
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM activity WHERE id=?", (identifier,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json"))
        value.pop("origin_key")
        return value

    def export(self, **filters):
        """以固定快照分批导出 JSONL，导出过程中新增记录留给下次导出"""
        where, args = self.filters(**filters)
        cte, polling_args = self.polling_cte(**filters)
        # 流式迭代串行执行，但框架可能将下一批调度到另一线程
        with closing(self.connect(check_same_thread=False)) as conn:
            conn.execute("BEGIN")
            snapshot = self._cursor(conn)
            after = 0
            while True:
                rows = conn.execute(
                    cte + f"SELECT * FROM activity WHERE {where} AND id>? AND id<=? "
                    "ORDER BY id LIMIT 200",
                    (*polling_args, *args, after, snapshot),
                ).fetchall()
                if not rows:
                    return
                for row in rows:
                    value = dict(row)
                    value["payload"] = json.loads(value.pop("payload_json"))
                    value.pop("origin_key")
                    yield dump(value) + "\n"
                after = rows[-1]["id"]

    def import_history(self, db):
        """按原时间补录历史，写入失败留待重启重试，已成功记录按来源去重"""
        with closing(self.connect()) as conn:
            if conn.execute("SELECT 1 FROM metadata WHERE key='history_imported'").fetchone():
                return
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
        rows = db.all(
            "SELECT m.*,c.project_id FROM messages m "
            "LEFT JOIN conversations c ON c.id=m.conversation_id "
            "WHERE m.created_at>=? ORDER BY m.created_at DESC LIMIT ?",
            (cutoff, self.max_records),
        )
        events = db.all(
            "SELECT e.*,j.project_id,j.conversation_id FROM events e "
            "LEFT JOIN jobs j ON j.id=e.job_id "
            "WHERE e.created_at>=? ORDER BY e.created_at DESC LIMIT ?",
            (cutoff, self.max_records),
        )
        pending = [
            (row["created_at"], f"message:{row['id']}", "ai", row["role"], row["text"], row)
            for row in rows
        ] + [
            (
                row["created_at"],
                f"event:{row['id']}",
                "task",
                row["kind"],
                str(row["data"].get("text", row["kind"])),
                row,
            )
            for row in events
        ]
        imported = True
        for stamp, key, category, event, title, row in sorted(pending)[-self.max_records :]:
            if stamp >= cutoff:
                if not self.write(
                    category,
                    event,
                    title,
                    row,
                    created_at=stamp,
                    source="history",
                    level="error" if event in {"error", "failed"} else "info",
                    origin_key=key,
                    job_id=row.get("job_id") or "",
                    conversation_id=row.get("conversation_id") or "",
                    project_id=row.get("project_id") or "",
                ):
                    imported = False
        if not imported:
            return
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO metadata VALUES ('history_imported','1')")
