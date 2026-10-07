"""从插件的纯配置模型生成清单 schema、示例和配置目录"""

import argparse
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "src/resume_maker/plugin_packages"
BEGIN = "<!-- BEGIN GENERATED SETTINGS -->"
END = "<!-- END GENERATED SETTINGS -->"


def json_text(value):
    """固定 JSON 编码和换行以便检查生成产物"""
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def generated_files():
    """只扫描实际存在的配置模型，不在宿主维护可选插件名单"""
    result, edits, rows = {}, [], []
    for path in sorted(PACKAGES.glob("*/configuration.py")):
        module = importlib.import_module(
            "resume_maker.plugin_packages." + path.parent.name + ".configuration"
        )
        model = module.Settings
        manifest_path = path.with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        defaults = model().model_dump(mode="json")
        schema = model.model_json_schema()
        schema["x-resume-maker-strict"] = model.model_config.get("strict", False)
        manifest.update(config=defaults, config_schema=schema)
        result[manifest_path] = json_text(manifest)
        edits.append({"instance": manifest["id"], "operation": "replace", "value": defaults})
        for key, field in schema["properties"].items():
            bounds = f"{field.get('minimum', '—')} … {field.get('maximum', '—')}"
            rows.append(
                f"| `{manifest['id']}` | `{key}` | `{json.dumps(defaults[key])}` | {bounds} | "
                f"{field.get('description', '')} |"
            )
    result[ROOT / "examples/plugin-config.json"] = json_text(
        {"bundles": [{"name": "runtime", "edits": edits}], "startup": []}
    )
    document = ROOT / "docs/reference/plugin-settings.md"
    source = document.read_text(encoding="utf-8")
    before, rest = source.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    table = "\n\n| 插件 | 字段 | 默认值 | 范围 | 用途 |\n| --- | --- | --- | --- | --- |\n"
    result[document] = before + BEGIN + table + "\n".join(rows) + "\n\n" + END + after
    return result


def main():
    """检查模式拒绝模型和清单漂移，写入模式同步全部生成产物"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, content in generated_files().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if stale:
        raise SystemExit(
            "配置产物未同步，请运行 python scripts/sync_plugin_settings.py：" + ", ".join(stale)
        )


if __name__ == "__main__":
    main()
