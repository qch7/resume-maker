"""Windows 共享读取冲突不会破坏配置记录的原子发布"""

import json
from pathlib import Path

import pytest

from resume_maker.infrastructure import filesystem
from resume_maker.runtime.state import StateStore


@pytest.mark.parametrize("code", [5, 32, 33])
def test_state_write_survives_temporary_windows_reader(tmp_path, monkeypatch, code):
    """短暂占用期间保留旧记录，释放后原子发布完整新记录"""
    path = tmp_path / "host-transition.json"
    store = StateStore(tmp_path)
    old = {"state": "prepared", "payload": "合成旧记录"}
    new = {"state": "booting", "payload": "合成新记录"}
    store.write(path, old)
    original = Path.replace
    attempts, sleeps = [], []

    def occupied(source, target):
        """模拟另一个读取者或扫描器暂时拒绝文件替换"""
        attempts.append(source)
        assert json.loads(path.read_text(encoding="utf-8")) == old
        if len(attempts) <= 2:
            error = PermissionError("synthetic Windows sharing conflict")
            error.winerror = code
            raise error
        return original(source, target)

    monkeypatch.setattr(Path, "replace", occupied)
    monkeypatch.setattr(filesystem.time, "sleep", sleeps.append)
    store.write(path, new)
    assert json.loads(path.read_text(encoding="utf-8")) == new
    assert not path.with_suffix(".pending").exists()
    assert len(sleeps) == 2 and sum(sleeps) < 2


@pytest.mark.parametrize("code", [5, 32, 33, None, 13])
def test_state_write_preserves_old_record_after_replace_failure(tmp_path, monkeypatch, code):
    """持久共享冲突有限重试，其他权限错误立即返回并保留完整旧记录"""
    path = tmp_path / "plugins.json"
    store = StateStore(tmp_path)
    old, new = {"generation": 1}, {"generation": 2}
    store.write(path, old)
    attempts, sleeps = [], []
    error = PermissionError("synthetic denied replacement")
    if code is not None:
        error.winerror = code

    def denied(source, target):
        """持续拒绝替换以验证旧记录和暂存文件的保留"""
        attempts.append(source)
        raise error

    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr(filesystem.time, "sleep", sleeps.append)
    with pytest.raises(PermissionError) as result:
        store.write(path, new)
    assert result.value is error
    assert json.loads(path.read_text(encoding="utf-8")) == old
    assert json.loads(path.with_suffix(".pending").read_text(encoding="utf-8")) == new
    assert len(attempts) == (7 if code in {5, 32, 33} else 1)
    assert len(sleeps) == len(attempts) - 1 and sum(sleeps) < 2
