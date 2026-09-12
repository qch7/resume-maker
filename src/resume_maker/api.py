import asyncio
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .catalog import Catalog, Problem, need
from .config import Config
from .db import Database, dump, now, uid
from .documents import Documents, inspect_template
from .jobs import Jobs
from .models import Model, ProjectProfile, ProviderSettings, ResumeItem
from .providers import CodexProvider, ProviderError
from .sources import collect_snapshot, scan_collection
from .storage import create_backup


class ProjectInput(Model):
    name: str = Field(min_length=1, max_length=200)
    roots: list[str] = Field(min_length=1, max_length=30)


class DraftInput(Model):
    base_revision: str
    field: str
    value: Any = None
    version: int = Field(default=0, ge=0)


class SaveInput(Model):
    base_revision: str
    field: str
    expected_head: str


class MessageInput(Model):
    text: str = Field(min_length=1, max_length=30000)
    kind: str = "chat"
    base_revision: str
    scope: str = "all"
    request_key: str = Field(min_length=1, max_length=100)


class ConversationInput(Model):
    title: str | None = Field(default=None, max_length=200)
    input_draft: str | None = Field(default=None, max_length=30000)
    scope: str | None = None
    archived: bool | None = None


class ResumeInput(Model):
    name: str = Field(min_length=1, max_length=200)
    template_id: str | None = None
    items: list[ResumeItem]
    version: int = 0


class TemplateInput(Model):
    path: str
    name: str = ""
    start: int
    end: int


class PathInput(Model):
    path: str


def create_app(config: Config | None = None, provider=None) -> FastAPI:
    config = config or Config()
    config.prepare()
    db = Database(config.data_dir / "resume.db")
    catalog = Catalog(db)
    jobs = Jobs(db, catalog, config.data_dir, provider)
    documents = Documents(catalog, config.data_dir)

    @asynccontextmanager
    async def lifespan(_app):
        jobs.start()
        yield
        jobs.stop()

    app = FastAPI(title="Resume Maker", version=__version__, lifespan=lifespan)
    app.state.db, app.state.catalog, app.state.jobs = db, catalog, jobs
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def local_auth(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            origin = request.headers.get("origin")
            allowed = {f"http://127.0.0.1:{config.port}", f"http://localhost:{config.port}"}
            if origin and origin not in allowed:
                return JSONResponse({"detail": "不允许跨站访问本机文件接口。"}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-resume-token", ""), config.token):
                return JSONResponse({"detail": "会话已失效，请刷新页面。"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Problem)
    async def problem_handler(_request, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(ValidationError)
    async def validation_handler(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def missing_handler(_request, _exc):
        return JSONResponse({"detail": "文件或目录不存在，请检查路径。"}, status_code=404)

    @app.exception_handler(ValueError)
    async def value_handler(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ProviderError)
    async def provider_error_handler(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "instance_id": config.instance_id}

    @app.post("/api/shutdown")
    def shutdown():
        callback = getattr(app.state, "stop_server", None)
        if callback is None:
            raise Problem("请从运行服务器的终端关闭应用。")
        callback()
        return {"ok": True}

    @app.get("/api/state")
    def state():
        return {
            "projects": db.all(
                "SELECT p.*, MAX(p.updated_at, "
                "COALESCE((SELECT MAX(updated_at) FROM drafts "
                "WHERE project_id=p.id), p.updated_at), "
                "COALESCE((SELECT MAX(updated_at) FROM conversations "
                "WHERE project_id=p.id AND archived=0), p.updated_at)) AS activity_at "
                "FROM projects p WHERE p.archived=0 ORDER BY p.created_at"
            ),
            "conversations": db.all(
                "SELECT * FROM conversations WHERE archived=0 ORDER BY updated_at DESC"
            ),
            "resumes": db.all("SELECT * FROM resumes ORDER BY updated_at DESC"),
            "templates": db.all("SELECT * FROM templates ORDER BY created_at DESC"),
            "jobs": db.all(
                "SELECT id,project_id,conversation_id,kind,status,error,created_at,finished_at "
                "FROM jobs ORDER BY created_at DESC LIMIT 100"
            ),
        }

    @app.post("/api/projects/scan")
    def scan(body: PathInput):
        return scan_collection(Path(body.path))

    @app.post("/api/projects")
    def create_project(body: ProjectInput):
        return catalog.create_project(body.name, body.roots)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str, revision_id: str | None = None):
        project = catalog.project(project_id)
        selected = revision_id or project["head_revision"]
        return {
            "project": project,
            "working": catalog.working(project_id, selected),
            "revision_snapshot": db.one(
                "SELECT * FROM snapshots WHERE id=?",
                (catalog.revision(selected, project_id)["snapshot_id"],),
            ),
            "revisions": db.all(
                "SELECT * FROM revisions WHERE project_id=? ORDER BY number DESC", (project_id,)
            ),
            "snapshots": db.all(
                "SELECT * FROM snapshots WHERE project_id=? ORDER BY created_at DESC LIMIT 10",
                (project_id,),
            ),
        }

    @app.get("/api/revisions/{revision_id}")
    def get_revision(revision_id: str):
        return catalog.revision(revision_id)

    @app.put("/api/projects/{project_id}/profile")
    def save_profile(project_id: str, body: ProjectProfile):
        catalog.project(project_id)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE projects SET profile_json=?,updated_at=? WHERE id=?",
                (dump(body.model_dump()), now(), project_id),
            )
        return catalog.project(project_id)

    @app.put("/api/projects/{project_id}/sources")
    def update_sources(project_id: str, body: ProjectInput):
        catalog.project(project_id)
        roots = [str(Path(p).expanduser().resolve(strict=True)) for p in body.roots]
        if any(not Path(p).is_dir() for p in roots):
            raise Problem("来源必须是目录。")
        with db.transaction() as conn:
            conn.execute(
                "UPDATE projects SET name=?,roots_json=?,updated_at=? WHERE id=?",
                (body.name, dump(list(dict.fromkeys(roots))), now(), project_id),
            )
        return catalog.project(project_id)

    @app.post("/api/projects/{project_id}/snapshots")
    def snapshot(project_id: str):
        return collect_snapshot(db, config.data_dir, catalog.project(project_id))

    @app.put("/api/projects/{project_id}/draft")
    def put_draft(project_id: str, body: DraftInput):
        return catalog.put_draft(
            project_id, body.base_revision, body.field, body.value, body.version
        )

    @app.post("/api/projects/{project_id}/draft/discard")
    def discard_draft(project_id: str, body: DraftInput):
        catalog.discard_draft(project_id, body.base_revision, body.field, body.version)
        return catalog.working(project_id, body.base_revision)

    @app.post("/api/projects/{project_id}/revisions")
    def save_revision(project_id: str, body: SaveInput):
        return catalog.save_field(project_id, body.base_revision, body.field, body.expected_head)

    @app.post("/api/projects/{project_id}/restore")
    def restore_revision(project_id: str, body: SaveInput):
        return catalog.restore(project_id, body.base_revision, body.expected_head)

    @app.post("/api/projects/{project_id}/conversations")
    def create_conversation(project_id: str):
        return catalog.create_conversation(project_id, "新会话")

    @app.get("/api/conversations/archived")
    def archived_conversations():
        return db.all("SELECT * FROM conversations WHERE archived=1 ORDER BY updated_at DESC")

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str):
        return {
            "conversation": catalog.conversation(conversation_id),
            "messages": db.all(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",
                (conversation_id,),
            ),
            "proposals": db.all(
                "SELECT * FROM proposals WHERE conversation_id=? ORDER BY created_at",
                (conversation_id,),
            ),
            "jobs": db.all(
                "SELECT * FROM jobs WHERE conversation_id=? ORDER BY created_at", (conversation_id,)
            ),
        }

    @app.patch("/api/conversations/{conversation_id}")
    def patch_conversation(conversation_id: str, body: ConversationInput):
        catalog.conversation(conversation_id)
        values = body.model_dump(exclude_none=True)
        if values:
            with db.transaction() as conn:
                current = conn.execute(
                    "SELECT * FROM conversations WHERE id=?", (conversation_id,)
                ).fetchone()
                if any(current[key] != value for key, value in values.items()):
                    values["updated_at"] = now()
                conn.execute(
                    "UPDATE conversations SET "
                    + ",".join(f"{k}=?" for k in values)
                    + " WHERE id=?",
                    (*values.values(), conversation_id),
                )
        return catalog.conversation(conversation_id)

    @app.post("/api/conversations/{conversation_id}/rebuild")
    def rebuild_conversation(conversation_id: str):
        catalog.conversation(conversation_id)
        with db.transaction() as conn:
            active = conn.execute(
                "SELECT id FROM jobs WHERE conversation_id=? AND status IN ('running','queued')",
                (conversation_id,),
            ).fetchone()
            if active:
                raise Problem("请先取消或等待当前任务完成。", 409)
            conn.execute(
                "UPDATE conversations SET provider_thread_id=NULL WHERE id=?", (conversation_id,)
            )
            conn.execute(
                "INSERT INTO messages VALUES (?,?,NULL,'system',?,?)",
                (uid(), conversation_id, "下次请求将以当前经历和已保存历史重建模型上下文。", now()),
            )
        return {"ok": True}

    @app.post("/api/conversations/{conversation_id}/messages")
    def message(conversation_id: str, body: MessageInput):
        return jobs.submit(
            conversation_id, body.text, body.kind, body.base_revision, body.scope, body.request_key
        )

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        jobs.cancel(job_id)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/events")
    async def events(job_id: str, request: Request, after: int = 0):
        need(db.one("SELECT id FROM jobs WHERE id=?", (job_id,)))

        async def stream():
            cursor = after
            while not await request.is_disconnected():
                rows = db.all(
                    "SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id", (job_id, cursor)
                )
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\ndata: {dump(row)}\n\n"
                job = db.one("SELECT status FROM jobs WHERE id=?", (job_id,))
                if job["status"] not in {"queued", "running"}:
                    yield f"event: done\ndata: {dump(job)}\n\n"
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/proposals/{proposal_id}/adopt")
    def adopt(proposal_id: str):
        return catalog.adopt(proposal_id)

    @app.post("/api/proposals/{proposal_id}/reject")
    def reject(proposal_id: str):
        with db.transaction() as conn:
            conn.execute(
                "UPDATE proposals SET status='rejected' WHERE id=? AND status='pending'",
                (proposal_id,),
            )
        return {"ok": True}

    @app.post("/api/resumes")
    def new_resume(body: ResumeInput):
        return catalog.save_resume(body.name, body.template_id, body.items)

    @app.put("/api/resumes/{resume_id}")
    def save_resume(resume_id: str, body: ResumeInput):
        return catalog.save_resume(body.name, body.template_id, body.items, resume_id, body.version)

    @app.post("/api/templates/inspect")
    def inspect(body: PathInput):
        return inspect_template(Path(body.path).expanduser().resolve(strict=True))

    @app.post("/api/templates")
    def import_template(body: TemplateInput):
        return documents.import_template(Path(body.path), body.name, body.start, body.end)

    @app.post("/api/resumes/{resume_id}/exports")
    def export(resume_id: str):
        return documents.export(resume_id)

    @app.get("/api/resumes/{resume_id}/exports")
    def export_history(resume_id: str):
        return db.all(
            "SELECT * FROM exports WHERE resume_id=? ORDER BY created_at DESC", (resume_id,)
        )

    @app.get("/api/exports/{export_id}/{file_name}")
    def export_file(export_id: str, file_name: str):
        record = need(db.one("SELECT * FROM exports WHERE id=?", (export_id,)))
        allowed = {"resume.docx", "resume.pdf", "manifest.json"}
        allowed.update(f"page-{i}.png" for i in range(1, (record["pages"] or 0) + 1))
        if file_name not in allowed:
            raise Problem("文件不存在。", 404)
        path = config.data_dir / "exports" / export_id / file_name
        if not path.exists():
            raise Problem("该文件尚未生成。", 404)
        return FileResponse(path, filename=file_name)

    @app.get("/api/settings")
    def settings():
        return {
            "provider": db.setting("provider", ProviderSettings().model_dump()),
            "data_dir": str(config.data_dir),
        }

    @app.put("/api/settings/provider")
    def provider_settings(body: ProviderSettings):
        db.set_setting("provider", body.model_dump())
        return body

    @app.get("/api/providers/codex")
    def inspect_provider():
        return CodexProvider().inspect(ProviderSettings.model_validate(db.setting("provider", {})))

    @app.post("/api/providers/codex/check")
    def check_provider():
        result = CodexProvider().run(
            workspace=config.data_dir / "workspaces" / f"check-{uid()}",
            prompt="连接测试。不要使用工具或读取文件。reply 写连接成功；"
            "experience=null，changes=[]，questions=[]。",
            thread_id=None,
            settings=ProviderSettings.model_validate(db.setting("provider", {})),
            cancelled=threading.Event(),
            emit=lambda *_: None,
        )
        return {"ok": True, "reply": result.reply}

    @app.post("/api/backups")
    def backup():
        output = create_backup(db, config.data_dir)
        return FileResponse(output, filename=f"resume-maker-{now()[:10]}.zip")

    if config.frontend.exists():
        assets = config.frontend / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        path = config.frontend / "index.html"
        if not path.exists():
            return HTMLResponse(
                "前端尚未构建，请运行 npm --prefix frontend run build。", status_code=503
            )
        return path.read_text(encoding="utf-8").replace("__RESUME_TOKEN__", config.token)

    return app
