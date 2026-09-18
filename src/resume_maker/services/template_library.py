"""模板库分类、收藏与真实首屏缩略图；组织信息独立于不可变模板映射。"""

import logging
import threading
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

from resume_maker.core.errors import Problem, need
from resume_maker.domain.templates import TEMPLATE_LIBRARY_KEY as KEY
from resume_maker.infrastructure.database import dump, now, uid, unpack
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.rendering import render_word
from resume_maker.services.template_cleanup import cleanup_template


class TemplateLibrary:
    """以数据库配置保存分类和 Like，缩略图按模板内容复用。"""

    def __init__(self, catalog, data_dir: Path, templates=None, previews=None):
        """绑定当前应用的数据目录，隔离缩略图生成锁。"""
        self.catalog, self.db, self.data_dir = catalog, catalog.db, data_dir
        self.preview_lock = threading.RLock()
        self.templates, self.previews = templates, previews
        self.stop_flag = threading.Event()
        self.worker = None

    def state(self):
        """返回组织信息，未设置的模板由客户端归入未分类。"""
        with self.db.connect() as conn:
            conn.execute("BEGIN")
            return self._state(conn)

    def _state(self, conn):
        """同一数据库快照返回组织信息、实时列表和全部简历引用数。"""
        state = self._read(conn)
        state["templates"] = [
            dict(row)
            for row in conn.execute(
                "SELECT id,name,created_at,(SELECT COUNT(*) FROM resumes "
                "WHERE template_id=templates.id) AS usage_count FROM templates "
                "WHERE json_type(mapping_json,'$.plan')='object' ORDER BY created_at DESC"
            )
        ]
        return state

    def update(self, template_id, changes):
        """原子修改名称和组织信息，保持模板标识、映射、文件及简历引用不变。"""
        changes = dict(changes)
        name = changes.pop("name", None)
        if name is not None:
            if template_id == "builtin":
                raise Problem("内置模板不能重命名。", 409)
            name = name.strip()
            if not name or len(name) > 200:
                raise Problem("模板名称须为 1–200 个字符。")
        with self.db.transaction() as conn:
            if template_id != "builtin":
                need(conn.execute("SELECT 1 FROM templates WHERE id=?", (template_id,)).fetchone())
            state = self._read(conn)
            if state["items"].get(template_id, {}).get("deleted_at"):
                raise Problem("该模板已移入回收站，请先恢复。", 409)
            category = changes.get("category_id")
            if category and not any(item["id"] == category for item in state["categories"]):
                raise Problem("分类已不存在，请重新选择。", 409)
            if name is not None:
                conn.execute("UPDATE templates SET name=? WHERE id=?", (name, template_id))
            item = state["items"].setdefault(template_id, {"category_id": "", "liked": False})
            item.update(changes)
            self._write(conn, state)
            return self._state(conn)

    def delete(self, template_id, permanent=False, cutoff=None):
        """拒绝删除被引用的模板；默认移入回收站，永久删除同步清理文件及数据库。"""
        if template_id == "builtin":
            raise Problem("内置模板是默认版式，不能删除。", 409)
        with (
            self.preview_lock,
            self.templates.lock if self.templates else nullcontext(),
            self.previews.lock if self.previews else nullcontext(),
            self.db.transaction() as conn,
        ):
            template = need(
                unpack(
                    conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
                ),
                "该模板不存在或已永久删除。",
            )
            used = conn.execute(
                "SELECT name FROM resumes WHERE template_id=? ORDER BY created_at", (template_id,)
            ).fetchall()
            if used:
                names = "、".join(row["name"] for row in used[:3])
                raise Problem(
                    f"模板被 {len(used)} 份简历引用（{names}），不能删除；请先更换模板。", 409
                )
            state = self._read(conn)
            item = state["items"].setdefault(template_id, {"category_id": "", "liked": False})
            if cutoff is not None and (
                not item.get("deleted_at") or datetime.fromisoformat(item["deleted_at"]) > cutoff
            ):
                return self._state(conn)
            if permanent:
                if not item.get("deleted_at"):
                    raise Problem("请先将模板移入回收站，再永久删除。", 409)
                others = [
                    unpack(row)
                    for row in conn.execute("SELECT * FROM templates WHERE id<>?", (template_id,))
                ]
                cleanup_template(self.data_dir, template, others, self.templates, self.previews)
                conn.execute("DELETE FROM templates WHERE id=?", (template_id,))
                del state["items"][template_id]
            else:
                item.setdefault("deleted_at", now())
            self._write(conn, state)
            return self._state(conn)

    def restore(self, template_id):
        """恢复模板及原分类收藏；到期清理与恢复共享写事务，不产生过期引用。"""
        with self.db.transaction() as conn:
            need(conn.execute("SELECT 1 FROM templates WHERE id=?", (template_id,)).fetchone())
            if not (self.data_dir / "templates" / template_id / "template.docx").is_file():
                raise Problem("模板文件已被清理，无法恢复；请完成永久删除或重新导入。", 409)
            state = self._read(conn)
            item = state["items"].get(template_id, {})
            item.pop("deleted_at", None)
            self._write(conn, state)
            return self._state(conn)

    def purge_expired(self, at=None):
        """逐项清理满三十天的模板，单项占用或文件错误留待下次重试。"""
        cutoff = (at or datetime.now(UTC)) - timedelta(days=30)
        for identifier, item in self.state()["items"].items():
            try:
                if item.get("deleted_at") and datetime.fromisoformat(item["deleted_at"]) <= cutoff:
                    self.delete(identifier, permanent=True, cutoff=cutoff)
            except (Problem, OSError, ValueError):
                logging.getLogger(__name__).exception("回收站模板清理失败：%s", identifier)

    def start(self):
        """启动时先补做过期清理，随后每分钟检查；不依赖打开模板库。"""
        self.purge_expired()
        self.stop_flag.clear()
        self.worker = threading.Thread(target=self._maintain, daemon=True, name="template-trash")
        self.worker.start()

    def _maintain(self):
        """可中断等待避免关闭时滞留后台清理线程。"""
        while not self.stop_flag.wait(60):
            self.purge_expired()

    def stop(self):
        """停止回收站定时器，等待当前清理结束再关闭其他模板服务。"""
        self.stop_flag.set()
        if self.worker:
            self.worker.join()

    def create_category(self, name):
        """新建非空且不重名的分类，不自动改变模板所属分类。"""
        name = name.strip()
        if not name or name in {"全部模板", "未分类", "我的喜欢", "回收站"}:
            raise Problem("请填写其他分类名称。")
        with self.db.transaction() as conn:
            state = self._read(conn)
            if any(item["name"].casefold() == name.casefold() for item in state["categories"]):
                raise Problem("此分类名称已存在。", 409)
            state["categories"].append({"id": uid(), "name": name})
            self._write(conn, state)
            return self._state(conn)

    def delete_category(self, category_id):
        """移除分类时将其中模板归回未分类，保留模板、收藏和简历引用。"""
        with self.db.transaction() as conn:
            state = self._read(conn)
            state["categories"] = [c for c in state["categories"] if c["id"] != category_id]
            for item in state["items"].values():
                if item["category_id"] == category_id:
                    item["category_id"] = ""
            self._write(conn, state)
            return self._state(conn)

    def _read(self, conn):
        """在同一写事务内读取最新组织信息。"""
        row = unpack(conn.execute("SELECT value_json FROM settings WHERE key=?", (KEY,)).fetchone())
        return row["value"] if row else {"categories": [], "items": {}}

    def _write(self, conn, state):
        """在调用方事务中保存组织信息，随数据库备份恢复。"""
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (KEY, dump(state)))

    def thumbnail(self, template_id):
        """渲染源模板首屏并缓存；不试填个人资料、不登记导出、不调用 AI。"""
        with self.preview_lock:
            return self._thumbnail(template_id)

    def _thumbnail(self, template_id):
        """持锁读取源文件，避免永久删除完成后迟到渲染重新写出缓存。"""
        data = None
        if template_id == "builtin":
            fingerprint = "builtin-v1"
        else:
            template = self.catalog.template(template_id, include_trashed=True)
            source = self.data_dir / "templates" / template_id / "template.docx"
            data = source.read_bytes()
            fingerprint = digest(data)
            if fingerprint != template["hash"]:
                raise Problem("模板文件已在程序外变化，请重新导入。")
        directory = self.data_dir / "templates" / ".previews" / fingerprint
        image = directory / "page-1.png"
        with self.preview_lock:
            if image.is_file():
                return image
            directory.mkdir(parents=True, exist_ok=True)
            source = directory / "source.docx"
            if data is not None:
                source.write_bytes(data)
            else:
                write_full_resume(source, builtin_sample(), [])
            pages, error = render_word(source, directory / "source.pdf")
            if not pages or not image.is_file():
                raise Problem(error or "模板预览生成失败，请重试。", 503)
        return image


def builtin_sample():
    """给内置真实排版器提供公开示例，缩略图不使用用户个人资料。"""
    from resume_maker.domain.resume import ResumeDocument

    return ResumeDocument.model_validate(
        {
            "personal": {
                "name": "你的姓名",
                "job_title": "求职意向 · 软件工程师",
                "phone": "138 0000 0000",
                "email": "hello@example.com",
                "location": "杭州",
            },
            "sections": [
                {
                    "id": "education",
                    "title": "教育背景",
                    "kind": "education",
                    "entries": [
                        {
                            "id": "school",
                            "title": "示例大学",
                            "subtitle": "计算机科学与技术 · 本科",
                            "period": "2022.09 — 2026.06",
                            "details": "主修课程：数据结构、操作系统、计算机网络、数据库原理",
                        }
                    ],
                },
                {"id": "projects", "title": "项目经历", "kind": "projects"},
                {
                    "id": "skills",
                    "title": "专业技能",
                    "kind": "text",
                    "entries": [
                        {
                            "id": "skill",
                            "title": "技术能力",
                            "details": (
                                "熟悉 Python、TypeScript 与常用开发工具。\n"
                                "具备良好的工程实践、团队协作与问题分析能力。"
                            ),
                        }
                    ],
                },
                {
                    "id": "honors",
                    "title": "荣誉与证书",
                    "kind": "text",
                    "entries": [
                        {
                            "id": "honor",
                            "title": "校级奖学金",
                            "period": "2025",
                            "details": "大学英语六级 · 软件设计师",
                        }
                    ],
                },
            ],
        }
    ).model_dump()
