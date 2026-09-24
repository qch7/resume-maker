"""分层约束覆盖不同导入写法，避免包入口绕过依赖检查"""

import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "source,forbidden",
    [
        ("from resume_maker import services", True),
        ("from resume_maker.services import jobs as queue", True),
        ("import resume_maker.api.app as app", True),
        ("from resume_maker import core", False),
        ("from resume_maker.core.errors import Problem", False),
    ],
)
def test_layer_check_covers_package_imports(tmp_path, source, forbidden):
    """领域模块拒绝反向依赖，合法下层导入仍可通过"""
    check = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check_quality.py"))[
        "check_file"
    ]
    package = tmp_path / "src" / "resume_maker"
    check.__globals__.update(ROOT=tmp_path, PACKAGE=package)
    path = package / "domain" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    errors, _ = check(path)
    assert bool(errors) is forbidden
    if forbidden:
        assert all("禁止 domain 依赖" in error for error in errors)
