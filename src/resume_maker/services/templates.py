"""模板分析、映射核对、试填与登记；复用现有 Provider 并支持取消。"""

import threading
import time
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from resume_maker.core.errors import Problem, need
from resume_maker.domain.models import ProviderSettings, ResumeItem
from resume_maker.domain.resume import ResumeDocument
from resume_maker.domain.templates import TemplatePlan
from resume_maker.infrastructure.database import dump, now, uid
from resume_maker.integrations.providers.base import Cancelled, Provider
from resume_maker.integrations.sources import digest, redact
from resume_maker.integrations.word.rendering import render_word
from resume_maker.integrations.word.template_fill import (
    fill_template,
    missing_targets,
)
from resume_maker.integrations.word.template_map import TemplatePackage
from resume_maker.services.catalog import Catalog
from resume_maker.services.template_analysis import analyze_plan, assess_plan
from resume_maker.services.template_cache import cache_path, cached_plan, remember_plan


class Templates:
    """管理独立模板分析，分析结果经核对后才进入已保存模板列表。"""

    def __init__(self, catalog: Catalog, data_dir: Path, provider: Provider):
        """保存实例依赖和受锁保护的任务状态，不在导入时启动线程。"""
        self.catalog, self.db, self.data_dir, self.provider = (
            catalog,
            catalog.db,
            data_dir,
            provider,
        )
        self.tasks, self.flags, self.threads = {}, {}, []
        self.started = {}
        self.lock = threading.Lock()
        self.stopped = False

    def analyze(
        self, path: Path, document: ResumeDocument, items: list[ResumeItem] | None = None
    ) -> dict:
        """先复制源文档为受控快照，再异步分析；源文件后续变化不影响确认结果。"""
        path = path.expanduser().resolve(strict=True)
        if path.suffix.lower() != ".docx":
            raise Problem("请先将 Word 文档另存为 .docx 格式。")
        return self._start(TemplatePackage(path), path.name, document, items or [])

    def repair(self, identifier, plan, document, items, feedback=""):
        """基于当前人工方案另开修正任务，原建议仍保留且不会被失败覆盖。"""
        return self._start(
            TemplatePackage(self.source(identifier)),
            self.get(identifier)["file_name"],
            document,
            items,
            plan,
            feedback,
        )

    def _start(self, package, file_name, document, items, initial=None, feedback=""):
        """统一准备分析副本与异步任务，校验项目引用后才调用模型。"""
        inventory = package.inventory()
        if inventory["warnings"]:
            raise Problem("；".join(inventory["warnings"]))
        projects = self.projects(items)
        with self.lock:
            if self.stopped:
                raise Problem("应用正在关闭。", 409)
            self.threads = [thread for thread in self.threads if thread.is_alive()]
            if self.threads:
                raise Problem("已有模板正在分析，请等待完成或取消。", 409)
            identifier = uid()
            directory = self.data_dir / "workspaces" / f"template-{identifier}"
            directory.mkdir(parents=True)
            # 保存刚解析的同一字节快照，防止分析和确认时读到不同文档。
            source = directory / "original.docx"
            package.write(source)
            task = {
                "id": identifier,
                "file_name": file_name,
                "status": "running",
                "activity": "正在识别字段和栏目…",
                "plan": None,
                "review": None,
                "inventory": inventory,
                "error": None,
                **new_progress(),
            }
            self.started[identifier] = time.monotonic()
            self.tasks[identifier] = task
            flag = self.flags[identifier] = threading.Event()
            settings = ProviderSettings.model_validate(self.db.setting("provider", {}))
            thread = threading.Thread(
                target=self._analyze,
                args=(identifier, directory, document, projects, settings, flag, initial, feedback),
                daemon=True,
                name=f"template-{identifier}",
            )
            self.threads.append(thread)
            thread.start()
            return deepcopy(task)

    def _analyze(
        self, identifier, directory, document, projects, settings, flag, initial, feedback
    ):
        """执行一次受超时控制的模型分析，取消或失败均不能登记模板。"""

        def emit(kind, data):
            """记录有界的公开活动和计量，取消后不再接受迟到事件。"""
            with self.lock:
                task = self.tasks[identifier]
                if task["status"] != "running" or flag.is_set():
                    return
                if kind == "activity":
                    text = redact(str(data.get("text", "分析中")))[:1000]
                    phase = data.get("type")
                    if phase in {"prepare", "analysis", "validation", "cache"}:
                        task["phase"] = phase
                    if isinstance(data.get("round"), int):
                        task["round"] = data["round"]
                    if text != task["activity"]:
                        task["cursor"] += 1
                        task["events"] = (
                            task["events"]
                            + [
                                {
                                    "id": task["cursor"],
                                    "text": text,
                                    "elapsed_ms": self._elapsed(task),
                                }
                            ]
                        )[-80:]
                        task["activity"] = text
                elif kind == "usage":
                    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
                        value = data.get(key)
                        if isinstance(value, int) and value >= 0:
                            task["usage"][key] = task["usage"].get(key, 0) + value
                elif kind == "metrics":
                    task["metrics"].append(
                        {key: data[key] for key in ("round", "prompt_chars", "images", "resumed")}
                    )

        try:
            package = TemplatePackage(directory / "original.docx")
            path = cache_path(self.data_dir, package, document, projects)
            hit = (
                cached_plan(path, package, document, projects)
                if initial is None and not feedback
                else None
            )
            if hit:
                emit(
                    "activity",
                    {"type": "cache", "text": "已复用相同模板的识别结果，当前资料覆盖检查通过"},
                )
                plan, review = hit
                attempts, repair_error = 0, None
            else:
                plan, review, attempts, repair_error = analyze_plan(
                    package,
                    self.provider,
                    directory,
                    document,
                    projects,
                    settings,
                    flag,
                    emit,
                    initial,
                    feedback,
                )
            with self.lock:
                if flag.is_set():
                    raise Cancelled("模板分析已取消。")
                task = self.tasks[identifier]
                task["elapsed_ms"] = self._elapsed(task)
                if review["ready"] and initial is None and not feedback:
                    remember_plan(path, plan)
                task.update(
                    reused=bool(hit),
                    phase="completed",
                    status="completed",
                    plan=plan.model_dump(),
                    review=review,
                    activity="已完成自动检查，请查看试填。"
                    if review["ready"]
                    else "已自动修正，请核对剩余疑问。",
                    attempts=attempts,
                    repair_error=redact(repair_error)[:2000] if repair_error else None,
                )
        except Exception as exc:
            with self.lock:
                task = self.tasks[identifier]
                task["elapsed_ms"] = self._elapsed(task)
                task.update(
                    phase="cancelled" if flag.is_set() else "failed",
                    status="cancelled" if flag.is_set() else "failed",
                    error=redact(str(exc))[:2000],
                )

    def get(self, identifier: str) -> dict:
        """读取当前实例的分析结果，关闭应用后需重新分析，已登记模板不受影响。"""
        with self.lock:
            task = need(self.tasks.get(identifier), "模板分析已不存在，请重新分析。")
            return {**deepcopy(task), "elapsed_ms": self._elapsed(task)}

    def _elapsed(self, task):
        """运行时使用单调时钟，完成或取消后冻结耗时；调用方持有状态锁。"""
        return (
            round((time.monotonic() - self.started[task["id"]]) * 1000)
            if task["status"] == "running"
            else task["elapsed_ms"]
        )

    def progress(self, identifier, after=0):
        """仅返回轻量进度与游标之后的活动，不复制或传输模板清单和映射。"""
        with self.lock:
            task = need(self.tasks.get(identifier), "模板分析已不存在，请重新分析。")
            value = {
                key: deepcopy(task[key])
                for key in (
                    "id",
                    "status",
                    "activity",
                    "error",
                    "phase",
                    "round",
                    "cursor",
                    "usage",
                    "reused",
                    "metrics",
                )
            }
            value["elapsed_ms"] = self._elapsed(task)
            value["events"] = [deepcopy(event) for event in task["events"] if event["id"] > after]
            return value

    def open(self, template_id: str) -> dict:
        """从已保存模板建立独立编辑快照，不调用 AI，也不修改原版本及简历引用。"""
        template = self.catalog.template(template_id)
        mapping = template["mapping"]
        source = self.data_dir / "templates" / template["id"] / "template.docx"
        data = source.read_bytes()
        if digest(data) != template["hash"]:
            raise Problem("模板文件已在程序外变化，请重新导入。")
        plan = TemplatePlan.model_validate(mapping["plan"])
        package = TemplatePackage(BytesIO(data))
        inventory = package.inventory()
        with self.lock:
            if self.stopped:
                raise Problem("应用正在关闭。", 409)
            identifier = uid()
            directory = self.data_dir / "workspaces" / f"template-{identifier}"
            directory.mkdir(parents=True)
            # 写回经过哈希核验的字节，之后的人工调整仅作用于这个副本。
            (directory / "original.docx").write_bytes(data)
            task = {
                "id": identifier,
                "file_name": template["name"],
                "status": "completed",
                "activity": "已打开保存的映射，修改后将保存为新版本。",
                "plan": plan.model_dump(),
                "review": package.review(plan),
                "inventory": inventory,
                "error": None,
                **new_progress(),
            }
            self.started[identifier] = time.monotonic()
            self.tasks[identifier] = task
            return deepcopy(task)

    def cancel(self, identifier: str) -> dict:
        """取消尚未结束的分析，迟到的模型结果不能重新发布。"""
        with self.lock:
            task = need(self.tasks.get(identifier), "模板分析不存在。")
            if task["status"] == "running":
                self.flags[identifier].set()
                task["elapsed_ms"] = self._elapsed(task)
                task.update(status="cancelled", phase="cancelled", activity="已取消")
        return self.get(identifier)

    def source(self, identifier: str) -> Path:
        """确认任务属于当前实例且分析完成，再取得内部快照路径。"""
        if self.get(identifier)["status"] != "completed":
            raise Problem("请先完成模板分析。", 409)
        return self.data_dir / "workspaces" / f"template-{identifier}" / "original.docx"

    def review(
        self,
        identifier: str,
        plan: TemplatePlan,
        document: ResumeDocument | None = None,
        items: list[ResumeItem] | None = None,
    ) -> dict:
        """对用户修改后的映射重新做完整校验。"""
        package = TemplatePackage(self.source(identifier))
        return (
            assess_plan(package, plan, document, self.projects(items or []))
            if document
            else package.review(plan)
        )

    def save(
        self,
        identifier: str,
        name: str,
        plan: TemplatePlan,
        document: ResumeDocument,
        items: list[ResumeItem],
    ) -> dict:
        """登记核对过的完整模板，原文件和映射一并保留供重复导出与备份。"""
        source = self.source(identifier)
        review = TemplatePackage(source).review(plan)
        if not review["ready"]:
            raise Problem("映射尚未完成，请处理校验问题和未识别内容。")
        missing = missing_targets(document, plan, self.projects(items))
        if missing:
            raise Problem("模板未覆盖这些已填写资料，请补充映射或隐藏：" + "、".join(missing))
        template_id = uid()
        directory = self.data_dir / "templates" / template_id
        directory.mkdir(parents=True)
        data = source.read_bytes()
        (directory / "original.docx").write_bytes(data)
        (directory / "template.docx").write_bytes(data)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO templates VALUES (?,?,?,?,?)",
                (
                    template_id,
                    name.strip() or self.get(identifier)["file_name"],
                    digest(data),
                    dump({"plan": plan.model_dump()}),
                    now(),
                ),
            )
        return self.db.one("SELECT * FROM templates WHERE id=?", (template_id,))

    def preview(
        self, identifier: str, plan: TemplatePlan, document: ResumeDocument, items: list[ResumeItem]
    ) -> dict:
        """使用当前资料试填，校验固定引用与选择后生成 Word 和可用的分页预览。"""
        source = self.source(identifier)
        projects = self.projects(items)
        # 预览文件使用独立标识，迟到响应或新预览不会覆盖正在查看的文件。
        preview_id = uid()
        directory = source.parent / preview_id
        directory.mkdir()
        output = directory / "resume.docx"
        try:
            fill_template(source, output, plan, document.model_dump(), projects)
        except Exception:
            if not any(directory.iterdir()):
                directory.rmdir()
            raise
        pages, error = render_word(output, directory / "resume.pdf")
        return {"id": preview_id, "pages": pages, "render_error": error}

    def projects(self, items: list[ResumeItem]) -> list[dict]:
        """校验固定项目和亮点引用，保存与试填使用同一份资料覆盖规则。"""
        if len({item.project_id for item in items}) != len(items):
            raise Problem("项目引用不能重复。")
        projects = []
        for item in items:
            revision = self.catalog.revision(item.revision_id, item.project_id)
            valid = {point["id"] for point in revision["content"]["highlights"]}
            if not set(item.highlight_ids) <= valid or len(item.highlight_ids) != len(
                set(item.highlight_ids)
            ):
                raise Problem("请先提交项目草稿并用于当前简历，再试填模板。")
            projects.append({**item.model_dump(), "content": revision["content"]})
        return projects

    def stop(self):
        """关闭应用时取消分析并回收本服务的后台线程。"""
        with self.lock:
            self.stopped = True
            for flag in self.flags.values():
                flag.set()
        for thread in self.threads:
            thread.join(timeout=8)


def new_progress():
    """为每个任务分配独立进度容器，避免共享活动列表与统计。"""
    return {
        "phase": "prepare",
        "round": 0,
        "elapsed_ms": 0,
        "events": [],
        "cursor": 0,
        "usage": {},
        "metrics": [],
        "reused": False,
    }
