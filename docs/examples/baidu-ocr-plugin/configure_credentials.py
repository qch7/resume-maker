"""交互创建外部凭据文件，密钥不出现在命令参数或普通配置中"""

import argparse
import getpass
import json
import os
from pathlib import Path


def write_credentials(path: Path, api_key: str, secret_key: str) -> None:
    """独占创建凭据文件，已有文件保持不变"""
    if not api_key.strip() or not secret_key.strip():
        raise ValueError("API Key 和 Secret Key 不能为空")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"api_key": api_key.strip(), "secret_key": secret_key.strip()}, stream)


def main() -> None:
    """从隐藏输入读取密钥，只打印生成文件的绝对路径"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output.expanduser().resolve()
    api_key = getpass.getpass("百度 API Key: ")
    secret_key = getpass.getpass("百度 Secret Key: ")
    write_credentials(output, api_key, secret_key)
    print(output)


if __name__ == "__main__":
    main()
