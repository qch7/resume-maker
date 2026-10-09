"""实例资料的隔离、原子更新及关闭后的保留规则"""

import pytest

from resume_maker.core.errors import Problem
from resume_maker.infrastructure.database import Database
from resume_maker.infrastructure.instance_data import InstanceDataStore


def test_instance_data_survives_close_without_crossing_namespaces(tmp_path):
    """同名键按实例隔离，旧句柄失效后新句柄仍可读取正式资料"""
    db = Database(tmp_path / "data.db")
    first = InstanceDataStore(db, "example.one", "workspace")
    second = InstanceDataStore(db, "example.two", "workspace")
    first.set("value", {"name": "合成资料一"}, 0)
    second.set("value", {"name": "合成资料二"}, 0)
    first.get("value").value["name"] = "本地副本"
    assert first.get("value").value["name"] == "合成资料一"
    first.close()
    with pytest.raises(Problem, match="已关闭"):
        first.get("value")
    assert (
        InstanceDataStore(db, "example.one", "workspace").get("value").value["name"] == "合成资料一"
    )
    assert second.get("value").value["name"] == "合成资料二"


@pytest.mark.parametrize("temporary", [False, True])
def test_instance_transaction_conflict_rolls_back_every_key(tmp_path, temporary):
    """一项发生版本冲突时整组更新撤销，删除标记阻止旧副本覆盖"""
    db = Database(tmp_path / "data.db")
    store = InstanceDataStore(db, "example.one", "workspace", temporary)
    store.set("first", 1, 0)
    with pytest.raises(Problem, match="已变化"):
        with store.transaction() as transaction:
            transaction.set("second", 2, 0)
            transaction.set("first", 3, 0)
    assert store.get("second").version == 0
    assert store.get("first").value == 1
    with pytest.raises(Problem, match="已结束"):
        transaction.get("first")
    deleted = store.delete("first", 1)
    assert deleted.deleted and deleted.version == 2
    with pytest.raises(Problem, match="已变化"):
        store.set("first", 4, 1)
    stored_null = store.set("first", None, 2)
    assert stored_null.value is None and not stored_null.deleted
    if temporary:
        assert db.all("SELECT key FROM settings WHERE key LIKE 'plugin-instance:%'") == []
    store.close()
