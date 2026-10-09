"""备份可读取的非执行插件资料描述和资源引用规则"""

import json
import re
from pathlib import Path

from resume_maker.core.errors import Problem

CATALOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS plugin_data_catalog (
    plugin_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK(schema_version > 0),
    descriptor_json TEXT NOT NULL,
    package_version TEXT NOT NULL
);
"""


def builtin_descriptors():
    """从代码包读取初始描述，缺包时数据库中的持久目录册仍保留"""
    root = Path(__file__).parents[1] / "plugin_packages"
    return {
        json.loads(path.parent.parent.joinpath("manifest.json").read_text(encoding="utf-8"))[
            "id"
        ]: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*/data/descriptor.json"))
    }


def initialize_catalog(conn, selected=None):
    """初始化持久资料描述，关闭或缺少插件仍可发现附件"""
    descriptors = builtin_descriptors()
    for owner, descriptor in descriptors.items():
        if selected is not None and owner not in selected:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO plugin_data_catalog VALUES (?,?,?,?)",
            (owner, 1, json.dumps(descriptor, ensure_ascii=False), "1.0.0"),
        )


def value_at(record, path):
    """只解释点分隔数据路径，不执行表达式或代码"""
    result = record
    for key in path.split("."):
        if not isinstance(result, dict):
            return None
        result = result.get(key)
    return result


def resource_records(conn):
    """由已存资料目录枚举资源，查询标识符和相对路径均受固定语法约束"""
    rows = conn.execute("SELECT plugin_id,descriptor_json FROM plugin_data_catalog").fetchall()
    resources = []
    for owner, raw in rows:
        descriptor = json.loads(raw)
        if descriptor.get("backup") is False:
            continue
        for folder in descriptor.get("folders", []):
            if folder.startswith("plugin-data/"):
                validate_folder(owner, folder)
                resources.append({"owner": owner, "path": folder, "files": ["*"], "optional": True})
        for collection in descriptor.get("resources", []):
            root = collection["root"]
            table = collection.get("table", "settings")
            if not re.fullmatch(r"[a-z][a-z0-9-]*", root) or not re.fullmatch(r"[a-z_]+", table):
                raise Problem(f"插件 {owner} 的资源描述无效。")
            if table == "settings":
                prefix = collection["prefix"]
                if not isinstance(prefix, str) or "%" in prefix:
                    raise Problem("资料键前缀包含不允许的匹配符。")
                values = [
                    json.loads(row[0])
                    for row in conn.execute(
                        "SELECT value_json FROM settings WHERE substr(key,1,?)=?",
                        (len(prefix), prefix),
                    )
                ]
            elif not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            else:
                values = [{"id": row[0]} for row in conn.execute(f'SELECT id FROM "{table}"')]
            for value in values:
                if collection.get("when") and not value_at(value, collection["when"]):
                    continue
                if collection.get("state") and value.get("state") != collection["state"]:
                    continue
                identifier = value_at(value, collection.get("id", "id"))
                if not isinstance(identifier, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]+", identifier
                ):
                    raise Problem(f"插件 {owner} 的资源标识无效。")
                resources.append(
                    {
                        "owner": owner,
                        "path": f"{root}/{identifier}",
                        "files": collection.get("files", ["*"]),
                    }
                )
    return resources


def validate_folder(owner, folder):
    """插件私有资料固定到独立命名空间，描述文件不能越权引用宿主目录"""
    from pathlib import PurePosixPath

    path = PurePosixPath(folder)
    if (
        path.as_posix() != folder
        or path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 2
        or path.parts[:2] != ("plugin-data", owner)
        or any(char in folder for char in ("\\", ":", "\x00"))
    ):
        raise Problem("外部插件资料目录须位于 plugin-data/<插件ID> 内。", 409)


def validate_descriptor(owner, descriptor, external):
    """外部非执行描述只能引用自己声明的表、设置和资料目录"""
    if not external:
        return
    prefix = "plugin_" + re.sub(r"[.-]", "_", owner) + "_"
    if any(not name.startswith(owner + ":") for name in descriptor.get("settings", [])):
        raise Problem("外部插件设置须使用自身命名空间。", 409)
    if any(
        not name.startswith(owner + ":") or "%" in name
        for name in descriptor.get("privacy_settings", [])
    ):
        raise Problem("插件隐私资料描述须使用自身设置命名空间。", 409)
    if any(
        not re.fullmatch(r"[a-z_][a-z0-9_]*", name) or not name.startswith(prefix)
        for name in descriptor.get("tables", [])
    ):
        raise Problem("外部插件表须使用自身命名空间。", 409)
    for folder in descriptor.get("folders", []):
        validate_folder(owner, folder)
    if descriptor.get("resources"):
        raise Problem("外部插件附件请使用系统 assets 或命名空间资料目录。", 409)


def descriptors(conn):
    """返回纯资料元信息，不从备份读取任何维护入口或执行代码"""
    return [
        {
            "id": row[0],
            "schema_version": row[1],
            "descriptor": json.loads(row[2]),
            "package_version": row[3],
        }
        for row in conn.execute("SELECT * FROM plugin_data_catalog ORDER BY plugin_id")
    ]


def check_versions(conn, manifests):
    """已安装代码必须明确支持现有资料版本，未知更高版本拒绝写入"""
    for owner, version in conn.execute("SELECT plugin_id,schema_version FROM plugin_data_catalog"):
        manifest = manifests.get(owner)
        if manifest and manifest.data and version not in manifest.data.writes:
            raise Problem(f"插件 {owner} 不能写入资料版本 {version}，请先执行数据维护。", 409)


def data_blockers(db, manifests, locations):
    """不修改资料即可识别不兼容版本和未初始化表，允许最小系统继续访问资料"""
    blocked = {}
    with db.connect() as conn:
        versions = dict(conn.execute("SELECT plugin_id,schema_version FROM plugin_data_catalog"))
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for owner, manifest in manifests.items():
            if manifest.data is None:
                continue
            if owner in versions and versions[owner] not in manifest.data.writes:
                blocked[owner] = (
                    f"资料版本 {versions[owner]} 不可写，请停机执行插件资料维护；原资料已保留"
                )
            elif owner in locations and set(manifest.data.tables) - tables:
                blocked[owner] = "插件私有表尚未初始化，请停机执行插件资料维护"
    return blocked


def synchronize_catalog(db, manifests, locations):
    """登记已验证清单的数据归属，停用不删除目录册或重写未知版本"""
    builtins = builtin_descriptors()
    with db.transaction() as conn:
        check_versions(conn, manifests)
        for owner, manifest in manifests.items():
            if manifest.data is None:
                continue
            descriptor = {**manifest.data.model_dump(), **builtins.get(owner, {})}
            if manifest.data.descriptor:
                location = locations.get(owner)
                if location is None:
                    raise Problem(f"插件 {owner} 缺少数据描述安装位置。", 409)
                path = (location / manifest.data.descriptor).resolve()
                if not path.is_relative_to(location) or path.suffix != ".json":
                    raise Problem("插件数据描述路径无效。", 409)
                descriptor.update(json.loads(path.read_text(encoding="utf-8")))
            validate_descriptor(owner, descriptor, owner in locations)
            if owner in locations:
                actual = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if set(descriptor.get("tables", [])) - actual:
                    raise Problem(f"插件 {owner} 尚未初始化资料表，请先执行数据维护。", 409)
            previous = conn.execute(
                "SELECT descriptor_json FROM plugin_data_catalog WHERE plugin_id=?", (owner,)
            ).fetchone()
            if previous:
                descriptor["folders"] = sorted(
                    set(descriptor.get("folders", []))
                    | set(json.loads(previous[0]).get("folders", []))
                )
                descriptor["privacy_settings"] = sorted(
                    set(descriptor.get("privacy_settings", []))
                    | set(json.loads(previous[0]).get("privacy_settings", []))
                )
            conn.execute(
                "INSERT OR IGNORE INTO plugin_data_catalog VALUES (?,?,?,?)",
                (owner, manifest.data.schema_version, json.dumps(descriptor), manifest.version),
            )
            conn.execute(
                "UPDATE plugin_data_catalog SET descriptor_json=?,package_version=? "
                "WHERE plugin_id=?",
                (json.dumps(descriptor), manifest.version, owner),
            )
