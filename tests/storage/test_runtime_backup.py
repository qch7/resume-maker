"""备份压缩和在线任务共享资料时的写入及快照保证"""

import sqlite3
import threading
from contextlib import contextmanager
from zipfile import ZipFile

import pytest

from resume_maker.core.errors import Problem
from resume_maker.domain.models import AIResult
from resume_maker.infrastructure import storage
from resume_maker.infrastructure.database_policy import DatabasePolicy
from resume_maker.infrastructure.storage import create_backup, restore_backup
from resume_maker.infrastructure.task_supervisor import TaskSupervisor
from resume_maker.plugin_packages.ext_ai_conversation.services.jobs import Jobs


def test_zip_compression_allows_writes_and_preserves_frozen_database(
    catalog, tmp_path, monkeypatch
):
    """压缩期间的新写入及时成功，恢复的数据库仍保持压缩前的快照"""
    catalog.db.policy = DatabasePolicy(lock_timeout_seconds=0.1)
    errors, finished = [], threading.Event()
    catalog.db.set_setting("synthetic", "before")

    def write():
        """在压缩阶段模拟模型事件或草稿写入"""
        try:
            catalog.db.set_setting("synthetic", "after")
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            finished.set()

    worker = threading.Thread(target=write)

    class ConcurrentZip(ZipFile):
        """进入 ZIP 时固定写入和备份的先后关系"""

        def __enter__(self):
            """必须在压缩返回前观察到真实写事务成功"""
            result = super().__enter__()
            worker.start()
            assert finished.wait(2)
            assert errors == []
            return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(storage, "ZipFile", ConcurrentZip)
            archive = create_backup(catalog.db, catalog.db.path.parent)
    finally:
        if worker.ident:
            worker.join(2)
    restored = tmp_path / "restored"
    restore_backup(archive, restored)
    from resume_maker.infrastructure.database import Database

    assert Database(restored / "resume.db").setting("synthetic") == "before"
    assert catalog.db.setting("synthetic") == "after"


def test_backup_after_offline_migration_accepts_delete_journal(catalog, tmp_path):
    """离线迁移更换的数据库无需启动服务即可再次备份"""
    catalog.db.policy = DatabasePolicy(lock_timeout_seconds=0.1)
    catalog.db.set_setting("synthetic", "before")
    with catalog.db.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    archive = create_backup(catalog.db, catalog.db.path.parent)
    catalog.db.set_setting("synthetic", "after")
    restored = tmp_path / "restored"
    restore_backup(archive, restored)
    with sqlite3.connect(restored / "resume.db") as conn:
        assert (
            conn.execute("SELECT value_json FROM settings WHERE key='synthetic'").fetchone()[0]
            == '"before"'
        )


def test_model_completes_during_backup_without_duplicate_call(catalog, project, monkeypatch):
    """压缩中返回的模型事件和结果成功发布，不残留无人执行的运行任务"""
    catalog.db.policy = DatabasePolicy(lock_timeout_seconds=0.1)
    entered, release = threading.Event(), threading.Event()
    calls = []

    class Provider:
        """等待压缩开始才返回的本地模型替身"""

        def run(self, **kwargs):
            """产生一次用量事件及完整结果"""
            calls.append(1)
            entered.set()
            assert release.wait(3)
            kwargs["emit"]("usage", {"input_tokens": 1})
            return AIResult(reply="ok", experience=None, changes=[], questions=[])

    supervisor = TaskSupervisor(catalog.db)
    supervisor.start()
    jobs = Jobs(
        catalog.db,
        catalog,
        catalog.db.path.parent,
        Provider(),
        execution_queue=supervisor.scope("synthetic", 1, {}),
    )
    jobs.start()
    conversation = catalog.db.all("SELECT id FROM conversations")[0]
    job = jobs.submit(
        conversation["id"], "synthetic", "chat", project["head_revision"], "all", "one"
    )
    assert entered.wait(2)

    class ConcurrentZip(ZipFile):
        """在数据库和附件快照已经固定后放行模型"""

        def __enter__(self):
            """ZIP 尚未结束时，真实任务已经完成全部持久写入"""
            result = super().__enter__()
            release.set()
            with supervisor.condition:
                assert supervisor.condition.wait_for(lambda: not supervisor.owned, 2)
            assert (
                catalog.db.one("SELECT status FROM jobs WHERE id=?", (job["id"],))["status"]
                == "completed"
            )
            return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(storage, "ZipFile", ConcurrentZip)
            create_backup(catalog.db, catalog.db.path.parent)
        assert calls == [1] and jobs.active_tasks() == []
    finally:
        release.set()
        jobs.stop()
        supervisor.stop(timeout=3)


@pytest.mark.parametrize("cancel", [False, True])
def test_continuous_database_failure_retains_finalization_without_model_replay(
    catalog, project, monkeypatch, cancel
):
    """真实模型已经返回时，连续写入失败仅重试终态且保留关闭屏障"""
    entered, release, failed = threading.Event(), threading.Event(), threading.Event()
    writes_allowed = threading.Event()
    writes_allowed.set()
    calls = []
    original = catalog.db.transaction

    @contextmanager
    def transaction():
        """模型返回后暂时拒绝所有写入，读操作仍可检查真实状态"""
        if not writes_allowed.is_set():
            failed.set()
            raise sqlite3.OperationalError("synthetic write unavailable")
        with original() as conn:
            yield conn

    class Provider:
        """只发送一次合成模型结果"""

        def run(self, **kwargs):
            """失败从最终发布开始，避免重试真实模型"""
            calls.append(1)
            entered.set()
            assert release.wait(3)
            if cancel:
                kwargs["cancelled"].set()
            writes_allowed.clear()
            return AIResult(reply="ok", experience=None, changes=[], questions=[])

    monkeypatch.setattr(catalog.db, "transaction", transaction)
    supervisor = TaskSupervisor(catalog.db)
    supervisor.start()
    jobs = Jobs(
        catalog.db,
        catalog,
        catalog.db.path.parent,
        Provider(),
        execution_queue=supervisor.scope("synthetic", 1, {}),
    )
    jobs.start()
    remove = supervisor.attach("synthetic", jobs.active_tasks, jobs.cancel)
    conversation = catalog.db.all("SELECT id FROM conversations")[0]
    try:
        job = jobs.submit(
            conversation["id"], "synthetic", "chat", project["head_revision"], "all", "one"
        )
        assert entered.wait(2)
        release.set()
        assert failed.wait(2)
        with supervisor.condition:
            assert supervisor.condition.wait_for(lambda: not supervisor.owned, 2)
        assert calls == [1]
        assert len(supervisor.active({"synthetic"})) == 1
        assert job["id"] not in jobs.cancel_flags
        with pytest.raises(Problem, match="租约"):
            supervisor.wait_owned("synthetic", timeout=0.01)
        writes_allowed.set()
        with supervisor.condition:
            assert supervisor.condition.wait_for(lambda: not supervisor.recoveries, 2)
        status = catalog.db.one("SELECT status FROM jobs WHERE id=?", (job["id"],))["status"]
        assert status == ("cancelled" if cancel else "failed")
        assert calls == [1] and jobs.active_tasks() == []
        assert catalog.db.all("SELECT id FROM messages WHERE role='assistant'") == []
    finally:
        writes_allowed.set()
        release.set()
        jobs.stop()
        remove()
        supervisor.stop(timeout=3)
