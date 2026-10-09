"""只用标准库构建独立可安装包，构建不读取任何个人凭据"""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

RELEASE_FILES = (
    "manifest.json",
    "LICENSE",
    "README.md",
    "DEVELOPMENT-NOTES.md",
    "configure_credentials.py",
    "python/plugin.py",
    "client/index.js",
)


def build(output: Path) -> Path:
    """明确枚举发布文件，生成可复现的 ZIP 和完整摘要清单"""
    root = Path(__file__).resolve().parent
    files = {name: (root / name).read_bytes() for name in RELEASE_FILES}
    index = {
        name: {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        for name, raw in files.items()
    }
    files["artifacts.json"] = json.dumps(index, sort_keys=True, ensure_ascii=False).encode("utf-8")
    output = output.resolve()
    if output.suffix != ".rmp":
        raise ValueError("输出文件必须使用 .rmp 扩展名")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        for name, raw in sorted(files.items()):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return output


def main() -> None:
    """构建包并输出完整文件的 SHA-256，供下载校验使用"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = build(parser.parse_args().output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".rmp.sha256").write_text(digest + "\n", encoding="ascii")
    print(output)
    print("SHA-256: " + digest)


if __name__ == "__main__":
    main()
