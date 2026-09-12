"""从任意工作目录运行项目完整检查，首个失败立即返回对应退出码。"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """依次校验注释、架构、格式、测试及前端构建，避免失败被后续命令掩盖。"""
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("请先安装 Node.js 22.16+ 和 npm。")
    commands = [
        [sys.executable, "scripts/check_quality.py"],
        [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
        [sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
        [sys.executable, "-m", "pytest", "-q"],
        [npm, "--prefix", "frontend", "run", "check"],
        [npm, "--prefix", "frontend", "run", "build"],
    ]
    for command in commands:
        print(f"执行：{' '.join(command)}", flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
