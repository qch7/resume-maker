"""使用标准库构建独立插件包，无需导入主工程或测试辅助代码"""

import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile


def main() -> None:
    """打包明确列出的发布文件并生成完整摘要清单"""
    root = Path(__file__).resolve().parent
    output = Path(sys.argv[1]).resolve()
    files = {
        name: (root / name).read_bytes()
        for name in ("manifest.json", "LICENSE", "python/plugin.py", "client/index.js")
    }
    index = {
        name: {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        for name, raw in files.items()
    }
    files["artifacts.json"] = json.dumps(index).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    print(output)


if __name__ == "__main__":
    main()
