"""在独立源码副本中逐个移除可选包，并验证全部移除后的构建及业务闭环"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from resume_maker.core.process_environment import EnvironmentPolicy, process_environment

ROOT = Path(__file__).resolve().parents[1]
SEED = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from resume_maker.api import create_app
from resume_maker.core.config import Config
app = create_app(Config(data_dir=Path(sys.argv[2]), profile="standard", token="synthetic"))
assert Path(__import__("resume_maker").__file__).is_relative_to(Path(sys.argv[1]))
app.state.services.db.set_setting("retained:plugin-data", {"value": "synthetic"})
app.state.services.db.activity.write("ai", "retained", "synthetic history")
app.state.runtime.close()
"""
SMOKE = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
from resume_maker.api import create_app
from resume_maker.core.config import Config
missing = set(sys.argv[3].split(","))
config = Config(data_dir=Path(sys.argv[2]), token="synthetic")
app = create_app(config)
assert not (missing & app.state.runtime.definitions.keys())
assert not (missing & app.state.runtime.selected)
assert missing <= app.state.runtime.desired
assert missing <= app.state.runtime.blocked.keys()
assert app.state.services.db.setting("retained:plugin-data") == {"value": "synthetic"}
assert app.state.services.db.activity.page()["total"] >= 1
with TestClient(app, headers={"x-resume-token": config.token}) as client:
    caps = client.get("/api/capabilities").json()
    assert caps["ready"] and not (missing & {value["id"] for value in caps["client"]})
    client.headers["x-resume-generation"] = str(caps["generation"])
    response = client.post("/api/projects", json={"name": "synthetic project"})
    assert response.status_code == 200, response.text
    project = response.json()
    response = client.post("/api/resumes", json={"name": "synthetic resume",
        "items": [{"project_id": project["id"], "revision_id": project["head_revision"],
            "highlight_ids": []}], "document": {"personal": {"name": "synthetic"},
            "sections": [{"id": "projects", "title": "Projects", "kind": "projects"}]}})
    assert response.status_code == 200, response.text
    resume = response.json()
    from resume_maker.runtime.host import Contribution
    from resume_maker.sdk.documents import DocumentRenderer
    host = app.state.runtime
    key = ("documents.renderers", "ext.word/default")
    if item := host.contributions.get(key):
        host.contributions[key] = Contribution(item.owner, item.point, item.identifier,
            DocumentRenderer("1.0.0", lambda *_: (None, "synthetic matrix")))
    export = client.post(
        f"/api/resumes/{resume['id']}/exports", params={"version": resume["version"]}
    )
    assert export.status_code == 200, export.text
    assert client.get(f"/api/exports/{export.json()['id']}/resume.docx").status_code == 200
"""


def run_source(script, target, data, missing=()):
    """每次使用全新解释器，只导入副本代码，避免缓存掩盖缺包导入"""
    command = [sys.executable, "-I", "-X", "utf8", "-c", script, str(target / "src"), str(data)]
    if missing:
        command.append(",".join(missing))
    subprocess.run(
        command,
        cwd=target,
        check=True,
        stdout=subprocess.DEVNULL,
        env=process_environment(EnvironmentPolicy.CANDIDATE),
    )


def frontend_ignore(directory, names):
    """只排除宿主旧产物，依赖包内部 dist 仍是构建必需输入"""
    return [
        name
        for name in names
        if name.endswith(".tsbuildinfo")
        or (name == "dist" and Path(directory).resolve() == ROOT / "frontend")
    ]


def main():
    """仅在本任务临时副本移动代码包，正式源码及资料均不参与清理"""
    sys.stdout.reconfigure(encoding="utf-8")
    temporary_root = ROOT / ".local/tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="plugin-removal-", dir=temporary_root) as temporary:
        target = Path(temporary).resolve()
        shutil.copytree(ROOT / "src", target / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "pyproject.toml", target / "pyproject.toml")
        shutil.copytree(
            ROOT / "frontend",
            target / "frontend",
            ignore=frontend_ignore,
        )
        packages = target / "src/resume_maker/plugin_packages"
        available = []
        for path in packages.glob("*/manifest.json"):
            identifier = json.loads(path.read_text(encoding="utf-8"))["id"]
            metadata = json.loads(path.with_name("package.json").read_text(encoding="utf-8"))
            if "minimal" not in metadata["resumeMaker"]["profiles"]:
                available.append((identifier, path.parent))
        parked = target / "removed"
        parked.mkdir()
        for identifier, package in sorted(available):
            assert package.resolve().is_relative_to(target)
            data = target / "data" / package.name
            run_source(SEED, target, data)
            destination = parked / package.name
            package.rename(destination)
            try:
                run_source(SMOKE, target, data, [identifier])
                print(f"缺包闭环通过：{identifier}", flush=True)
            finally:
                destination.rename(package)
        data = target / "data/all-optional-removed"
        run_source(SEED, target, data)
        for _, package in available:
            package.rename(parked / package.name)
        run_source(SMOKE, target, data, [identifier for identifier, _ in available])
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("插件移除构建验收需要 npm")
        result = subprocess.run(
            [npm, "--prefix", "frontend", "run", "build"],
            cwd=target,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        print(f"全部 {len(available)} 个可选代码包移除后，构建、启动、历史保留及 DOCX 导出通过。")


if __name__ == "__main__":
    main()
