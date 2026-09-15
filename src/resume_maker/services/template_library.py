"""模板库分类、收藏与真实首屏缩略图；组织信息独立于不可变模板映射。"""

import threading
from pathlib import Path

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import dump, uid, unpack
from resume_maker.integrations.sources import digest
from resume_maker.integrations.word.full_resume import write_full_resume
from resume_maker.integrations.word.rendering import render_word

KEY = "template-library"


class TemplateLibrary:
    """以数据库配置保存分类和 Like，缩略图按模板内容复用。"""

    def __init__(self, catalog, data_dir: Path):
        """绑定当前应用的数据目录，隔离缩略图生成锁。"""
        self.catalog, self.db, self.data_dir = catalog, catalog.db, data_dir
        self.preview_lock = threading.Lock()

    def state(self):
        """返回组织信息，未设置的模板由客户端归入未分类。"""
        return self.db.setting(KEY, {"categories": [], "items": {}})

    def update(self, template_id, changes):
        """在事务内合并单个模板的收藏或分类，避免不同入口相互覆盖。"""
        if template_id != "builtin":
            self.catalog.template(template_id)
        with self.db.transaction() as conn:
            state = self._read(conn)
            category = changes.get("category_id")
            if category and not any(item["id"] == category for item in state["categories"]):
                raise Problem("分类已不存在，请重新选择。", 409)
            item = state["items"].setdefault(template_id, {"category_id": "", "liked": False})
            item.update(changes)
            self._write(conn, state)
        return state

    def create_category(self, name):
        """新建非空且不重名的分类，不自动改变模板所属分类。"""
        name = name.strip()
        if not name or name in {"全部模板", "未分类", "我的喜欢"}:
            raise Problem("请填写其他分类名称。")
        with self.db.transaction() as conn:
            state = self._read(conn)
            if any(item["name"].casefold() == name.casefold() for item in state["categories"]):
                raise Problem("此分类名称已存在。", 409)
            state["categories"].append({"id": uid(), "name": name})
            self._write(conn, state)
        return state

    def delete_category(self, category_id):
        """移除分类时将其中模板归回未分类，保留模板、收藏和简历引用。"""
        with self.db.transaction() as conn:
            state = self._read(conn)
            state["categories"] = [c for c in state["categories"] if c["id"] != category_id]
            for item in state["items"].values():
                if item["category_id"] == category_id:
                    item["category_id"] = ""
            self._write(conn, state)
        return state

    def _read(self, conn):
        """在同一写事务内读取最新组织信息。"""
        row = unpack(conn.execute("SELECT value_json FROM settings WHERE key=?", (KEY,)).fetchone())
        return row["value"] if row else {"categories": [], "items": {}}

    def _write(self, conn, state):
        """在调用方事务中保存组织信息，随数据库备份恢复。"""
        conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (KEY, dump(state)))

    def thumbnail(self, template_id):
        """渲染源模板首屏并缓存；不试填个人资料、不登记导出、不调用 AI。"""
        data = None
        if template_id == "builtin":
            fingerprint = "builtin-v1"
        else:
            template = self.catalog.template(template_id)
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
