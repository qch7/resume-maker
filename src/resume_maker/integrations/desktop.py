"""调用本机文件管理器定位已由项目服务校验的来源文件"""

import subprocess
import sys
from pathlib import Path

from resume_maker.core.errors import Problem


def reveal_file(path: Path) -> None:
    """Windows 和 macOS 选中文件，其他桌面平台打开其所在目录"""
    if sys.platform == "win32":
        command = ["explorer.exe", "/select,", str(path)]
    elif sys.platform == "darwin":
        command = ["open", "-R", str(path)]
    else:
        command = ["xdg-open", str(path.parent)]
    try:
        subprocess.Popen(command)
    except OSError as exc:
        raise Problem("无法启动资源管理器，请确认本机桌面环境可用。") from exc
