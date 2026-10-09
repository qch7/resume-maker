"""持续闲置的工作台读取不重复聚合，变化和实例仍正确隔离"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from resume_maker.api import create_app
from resume_maker.core.config import Config
from resume_maker.infrastructure.database import Database
from resume_maker.plugin_packages.sys_workbench.services.workspace import Workspace


def test_unchanged_state_skips_aggregation_and_external_commit_invalidates(catalog):
    """同版本只核验变更标识，另一连接的实际提交立即触发重读"""
    calls = []

    def reader(conn):
        """计数真实聚合并从读取快照取得合成资料"""
        calls.append(1)
        return {"synthetic": conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]}

    workspace = Workspace(catalog.db, readers=[reader])
    try:
        body, version = workspace.poll(None)
        assert body
        for _ in range(10):
            assert workspace.poll(version) == (None, version)
        assert len(calls) == 1
        with catalog.db.connect() as conn:
            conn.execute("INSERT INTO settings VALUES ('synthetic', '{}')")
            conn.commit()
        newer, new_version = workspace.poll(version)
        assert newer and new_version != version
        assert len(calls) == 2
    finally:
        if hasattr(workspace, "stop"):
            workspace.stop()


def test_state_instances_and_contribution_changes_do_not_share_cache(tmp_path):
    """相同资料行数的实例仍隔离正文，贡献变化无需数据库写入也会失效"""
    contributions = []
    left = Workspace(
        Database(tmp_path / "left.db"),
        readers=[lambda _: {"value": "left"}],
        contributors=lambda: tuple(contributions),
    )
    right = Workspace(Database(tmp_path / "right.db"), readers=[lambda _: {"value": "right"}])
    try:
        body, version = left.poll(None)
        other, _ = right.poll(version)
        assert b"left" in body and b"right" in other
        contributions.append(
            SimpleNamespace(identifier="synthetic", value=lambda _, state: state.update(extra=True))
        )
        changed, newer = left.poll(version)
        assert changed and newer != version and b"extra" in changed
        left.stop()
        left.stop()
        with right.db.connect() as conn:
            conn.execute("SELECT 1")
    finally:
        left.stop()
        right.stop()


def test_legacy_storage_without_observer_keeps_changes_fresh(catalog):
    """旧存储未实现可选观察能力时继续完整读取，不能猜测缓存有效"""
    calls = []

    def reader(conn):
        """返回当前事务中的真实设置"""
        calls.append(1)
        return {
            "synthetic": conn.execute(
                "SELECT value_json FROM settings WHERE key='synthetic'"
            ).fetchone()[0]
        }

    storage = SimpleNamespace(connect=catalog.db.connect)
    catalog.db.set_setting("synthetic", "before")
    workspace = Workspace(storage, readers=[reader])
    try:
        body, etag = workspace.poll(None)
        assert b"before" in body
        catalog.db.set_setting("synthetic", "after")
        changed, _ = workspace.poll(etag)
        assert b"after" in changed and len(calls) == 2
    finally:
        workspace.stop()


def test_unmarked_dynamic_contribution_is_not_cached(catalog):
    """依赖内存的旧扩展无需修改协议即可在下次轮询发布变化"""
    value = ["before"]
    contribution = SimpleNamespace(
        identifier="dynamic", value=lambda _, state: state.update(extra=value[0])
    )
    workspace = Workspace(catalog.db, readers=[], contributors=lambda: [contribution])
    try:
        body, etag = workspace.poll(None)
        assert b"before" in body
        value[0] = "after"
        changed, _ = workspace.poll(etag)
        assert b"after" in changed
    finally:
        workspace.stop()


def test_http_conditional_state_with_builtin_contributions_is_fresh(tmp_path):
    """真实路由空闲返回无正文，业务提交后的下一轮带回新资料"""
    app = create_app(Config(data_dir=tmp_path / "data", token="test-token"))
    headers = {"x-resume-token": "test-token"}
    with TestClient(app) as client:
        initial = client.get("/api/state", headers=headers)
        assert initial.status_code == 200
        headers["if-none-match"] = initial.headers["etag"]
        for _ in range(5):
            response = client.get("/api/state", headers=headers)
            assert response.status_code == 304 and response.content == b""
        source = tmp_path / "source"
        source.mkdir()
        created = client.post(
            "/api/projects", json={"name": "synthetic", "roots": [str(source)]}, headers=headers
        )
        assert created.status_code == 200
        changed = client.get("/api/state", headers=headers)
        assert changed.status_code == 200
        assert changed.json()["projects"][0]["name"] == "synthetic"
        assert changed.headers["etag"] != initial.headers["etag"]
