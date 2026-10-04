"""检查后端中文函数说明和模块依赖方向"""

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "resume_maker"
CHINESE = re.compile(r"[\u4e00-\u9fff]")
FORBIDDEN = {
    "core": {"api", "services", "infrastructure", "integrations", "domain"},
    "domain": {"api", "services", "infrastructure", "integrations"},
    "infrastructure": {"api", "services"},
    "integrations": {"api", "services"},
    "services": {"api"},
    "runtime": {"api", "services", "plugins", "integrations"},
    "sdk": {"api", "services", "plugins", "runtime", "infrastructure", "integrations"},
}
OWNERS = {
    module: owner
    for owner, modules in json.loads(
        (PACKAGE / "plugins" / "ownership.json").read_text(encoding="utf-8")
    ).items()
    for module in modules
}


def owner_of(module):
    """属性导入和模块导入共用最长模块前缀归属"""
    return next(
        (
            OWNERS[key]
            for key in sorted(OWNERS, key=len, reverse=True)
            if module == key or module.startswith(key + ".")
        ),
        None,
    )


def check_file(path: Path) -> tuple[list[str], int]:
    """解析函数说明和包内导入，返回具体违规位置和检查到的函数数量"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(ROOT)
    layer = path.relative_to(PACKAGE).parts[0] if path.is_relative_to(PACKAGE) else ""
    errors, functions = [], 0
    source = (
        "resume_maker." + ".".join(path.relative_to(PACKAGE).with_suffix("").parts)
        if path.is_relative_to(PACKAGE)
        else ""
    )
    source_owner = owner_of(source)
    if layer == "services" and path.name != "__init__.py" and source_owner is None:
        errors.append(f"{relative} 未声明插件实现所有者")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions += 1
            if not CHINESE.search(ast.get_docstring(node) or ""):
                errors.append(f"{relative}:{node.lineno} {node.name} 缺少中文函数说明")
        modules = []
        if isinstance(node, ast.ImportFrom):
            if node.level and layer not in {"__init__.py", "cli.py"}:
                errors.append(f"{relative}:{node.lineno} 包内部请使用绝对导入")
            module = node.module or ""
            modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.Call) and node.args:
            if (isinstance(node.func, ast.Name) and node.func.id == "__import__") or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
            ):
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    modules = [node.args[0].value]
        for module in modules:
            target_owner = owner_of(module)
            if source_owner and target_owner and source_owner != target_owner:
                errors.append(
                    f"{relative}:{node.lineno} {source_owner} 不能导入 {target_owner} 私有实现，"
                    "请使用 SDK 协议及能力注入"
                )
            if module.startswith("resume_maker."):
                target = module.split(".")[1]
                if target in FORBIDDEN.get(layer, set()):
                    errors.append(f"{relative}:{node.lineno} 禁止 {layer} 依赖 {target}")
    return errors, functions


def main() -> None:
    """检查 Python 源码、测试和维护脚本并在违规时返回非零退出码"""
    # 脚本使用 UTF-8 输出以支持不同 Windows 语言和代码页
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    errors, functions = [], 0
    paths = [
        *PACKAGE.rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
        *(ROOT / "scripts").glob("*.py"),
    ]
    for path in sorted(paths):
        found, count = check_file(path)
        errors.extend(found)
        functions += count
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Python 质量检查通过：{functions} 个函数有中文说明，模块依赖方向有效。")


if __name__ == "__main__":
    main()
