"""验证直接读取当前来源、按引用留存，以及文件变化和取消时的证据降级"""

import json
import threading
from pathlib import Path

import pytest
from conftest import record_source_files
from test_jobs import wait_job

from resume_maker.domain.models import AIResult
from resume_maker.infrastructure.database import uid
from resume_maker.integrations import sources
from resume_maker.integrations.providers.base import Cancelled
from resume_maker.services.jobs import Jobs
from resume_maker.services.projects import Projects


def reference(path="README.md", source="source-0", quote="current content"):
    """构造含完整行号和引文的文件证据，供真实核对流程验证"""
    return {
        "source": source,
        "path": path,
        "line_start": 1,
        "line_end": 1,
        "quote": quote,
        "status": "document",
    }


def test_source_context_does_not_enumerate_or_read_project_files(catalog, project, monkeypatch):
    """来源定位不遍历或读取项目文件，因此目录数量和大文件不会挡住模型启动"""

    def unexpected(*args, **kwargs):
        """任何提前枚举或读取内容都意味着整库采集被重新引入"""
        pytest.fail("source setup must not scan or read project files")

    monkeypatch.setattr(sources.os, "walk", unexpected)
    monkeypatch.setattr(Path, "iterdir", unexpected)
    monkeypatch.setattr(Path, "read_bytes", unexpected)
    monkeypatch.setattr(Path, "read_text", unexpected)
    context = sources.project_sources(project)
    assert [item["path"] for item in context] == project["roots"]
    assert not catalog.db.all("SELECT id FROM snapshots")


def test_jobs_read_all_current_roots_and_only_archive_cited_files(catalog, tmp_path):
    """所有来源直接可读，续聊读取最新内容和重绑路径，历史快照不会成为输入"""
    roots = [tmp_path / f"component-{index}" for index in range(5)]
    for index, root in enumerate(roots):
        root.mkdir()
        (root / "README.md").write_text(f"component {index}", encoding="utf-8")
    project = catalog.create_project("Multi source", [str(root) for root in roots])
    data_dir = tmp_path / "data"
    old = record_source_files(catalog.db, data_dir, project)
    (roots[0] / "README.md").write_text("updated first source", encoding="utf-8")
    last_file = roots[-1] / "feature.custom"
    last_file.write_text("current content", encoding="utf-8")
    calls = []

    class ReadingProvider:
        """从收到的绝对路径实际读文件，模拟模型仅引用末尾子项目的功能"""

        def run(self, **kw):
            """在返回之前确认未采集新文件，再按当前路径生成回复和一次经历建议"""
            context = json.loads(kw["prompt"].split("本轮上下文数据：\n")[1])
            assert context["source_access"] == "direct-read-only"
            assert "snapshot_directory" not in context
            assert "fingerprint" not in context
            assert len(catalog.db.all("SELECT id FROM snapshots")) == (1 if not calls else 2)
            values = [
                (Path(item["path"]) / "README.md").read_text(encoding="utf-8")
                for item in context["source_directories"]
            ]
            cited = Path(context["source_directories"][-1]["path"]) / "feature.custom"
            quote = cited.read_text(encoding="utf-8")
            calls.append((values, quote))
            kw["emit"]("thread", {"id": kw["thread_id"] or uid()})
            content = None
            if context["task"] == "analysis":
                content = {
                    **context["current_experience"],
                    "highlights": [
                        {
                            "id": "last-source",
                            "title": "Last component",
                            "text": quote,
                            "evidence": [reference("feature.custom", "source-4", quote)],
                        }
                    ],
                }
            return AIResult(reply=quote, experience=content, changes=[], questions=[])

    jobs = Jobs(catalog.db, catalog, data_dir, ReadingProvider())
    conversation = catalog.db.one(
        "SELECT * FROM conversations WHERE project_id=?", (project["id"],)
    )
    jobs.start()
    try:
        first = jobs.submit(
            conversation["id"], "分析所有目录", "analysis", project["head_revision"], "all", uid()
        )
        completed = wait_job(catalog, first["id"])
        assert completed["status"] == "completed", completed["error"]
        assert calls[0] == (
            ["updated first source", "component 1", "component 2", "component 3", "component 4"],
            "current content",
        )
        record = catalog.db.one(
            "SELECT * FROM snapshots WHERE id=?", (completed["request"]["snapshot_id"],)
        )
        assert record["manifest"]["mode"] == "cited-files"
        assert [(item["source"], item["path"]) for item in record["manifest"]["files"]] == [
            ("source-4", "feature.custom")
        ]
        proposal = catalog.db.one("SELECT * FROM proposals WHERE job_id=?", (first["id"],))
        evidence = proposal["after"]["highlights"][0]["evidence"]
        assert evidence[0]["status"] == "document"
        catalog.adopt(proposal["id"])
        saved = catalog.save_revision(
            project["id"], project["head_revision"], project["head_revision"]
        )
        assert saved["snapshot_id"] == record["id"]
        assert saved["content"]["highlights"][0]["evidence"] == evidence

        last_file.write_text("changed before followup", encoding="utf-8")
        replacement = tmp_path / "new-source"
        replacement.mkdir()
        (replacement / "README.md").write_text("rebound source", encoding="utf-8")
        Projects(catalog).update_sources(
            project["id"], project["name"], [str(replacement), *map(str, roots[1:])]
        )
        second = jobs.submit(conversation["id"], "读取最新文件", "chat", saved["id"], "all", uid())
        completed = wait_job(catalog, second["id"])
        assert completed["status"] == "completed", completed["error"]
        assert calls[-1][0][0] == "rebound source"
        assert calls[-1][1] == "changed before followup"
        assert "snapshot_id" not in completed["request"]
        assert len(catalog.db.all("SELECT id FROM snapshots")) == 2
        assert sources.check_evidence(data_dir, record, evidence)[0]["status"] == "document"
        assert catalog.db.one("SELECT * FROM snapshots WHERE id=?", (old["id"],)) == old
    finally:
        jobs.stop()


def test_cited_files_have_no_old_size_or_suffix_limits(catalog, project, tmp_path):
    """单文件超过 512 KB、合计超过 25 MB 和自定义扩展名都能留存被引用证据"""
    root = Path(project["roots"][0])
    content = "current content\n" + "x\n" * (7 * 1024 * 1024)
    for name in ("first.custom", "second.custom"):
        (root / name).write_bytes(content.encode("utf-8"))
    references = [reference("first.custom"), reference("second.custom"), reference("first.custom")]
    record = sources.capture_evidence(
        catalog.db, tmp_path / "data", project, sources.project_sources(project), references
    )
    assert len(record["manifest"]["files"]) == 2
    assert record["manifest"]["total_bytes"] > 25 * 1024 * 1024
    assert not record["manifest"]["omitted"]
    assert all(
        item["status"] == "document"
        for item in sources.check_evidence(tmp_path / "data", record, references)
    )


def test_invalid_or_changed_citations_are_unverified(catalog, project, tmp_path):
    """失效路径、越界、敏感文件和已变化的引文均降级，正常引用仍然可核对"""
    root = Path(project["roots"][0])
    (root / "README.md").write_text("new content", encoding="utf-8")
    (root / ".env").write_text("private content", encoding="utf-8")
    (root / "binary.data").write_bytes(b"text\0binary")
    references = [
        reference("README.md", quote="old content"),
        reference("README.md", quote="new content"),
        reference("missing.py"),
        reference("../outside.txt"),
        reference(str(root / "README.md")),
        reference("README.md:stream"),
        reference(".env"),
        reference("binary.data"),
        reference(source="unknown"),
    ]
    record = sources.capture_evidence(
        catalog.db, tmp_path / "data", project, sources.project_sources(project), references
    )
    verified = sources.check_evidence(tmp_path / "data", record, references)
    assert [item["status"] for item in verified] == ["unverified", "document", *["unverified"] * 7]
    assert len(record["manifest"]["files"]) == 1
    assert len(record["manifest"]["omitted"]) == 7
    assert sources.check_evidence(tmp_path / "data", None, [references[1]])[0]["status"] == (
        "unverified"
    )


def test_cancelling_evidence_capture_cleans_partial_files(catalog, project, tmp_path, monkeypatch):
    """已开始写入引用文件后取消，也不会留下半成品目录或数据库记录"""
    data_dir = tmp_path / "data"
    cancelled = threading.Event()
    write_bytes = Path.write_bytes

    def cancel_after_write(path, data):
        """真实写出第一个临时文件后发出取消信号，覆盖清理路径"""
        result = write_bytes(path, data)
        cancelled.set()
        return result

    monkeypatch.setattr(Path, "write_bytes", cancel_after_write)
    with pytest.raises(Cancelled):
        sources.capture_evidence(
            catalog.db,
            data_dir,
            project,
            sources.project_sources(project),
            [reference()],
            cancelled,
        )
    assert not catalog.db.all("SELECT id FROM snapshots")
    assert not list((data_dir / "snapshots").iterdir())
