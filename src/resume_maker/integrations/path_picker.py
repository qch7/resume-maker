"""通过 Windows 原生公共对话框选择本机路径，不上传文件或执行路径中的命令。"""

import ctypes
import shutil
import sys
import threading
from pathlib import Path
from uuid import UUID

from resume_maker.core.errors import Problem

_dialog_lock = threading.Lock()
_CANCELLED = -2147023673  # HRESULT_FROM_WIN32(ERROR_CANCELLED)


def initial_directory(value: str, kind: str) -> Path:
    """优先打开已填路径或其所在目录，无效路径和命令名回退到可用目录。"""
    value = value.strip().strip('"')
    if kind == "executable" and value:
        value = shutil.which(value) or value
    if value:
        try:
            path = Path(value).expanduser()
            if path.is_dir():
                return path.resolve()
            if path.is_file():
                return path.resolve().parent
            if path.parent.is_dir() and path.parent != Path("."):
                return path.parent.resolve()
        except (OSError, ValueError):
            pass
    return Path.home()


def pick_path(kind: str, initial_path: str = "") -> str | None:
    """每次仅打开一个原生选择窗口；取消返回空值，错误不改变表单内容。"""
    if sys.platform != "win32":
        raise Problem("当前系统无法打开 Windows 选择窗口，请手动填写路径。", 501)
    if not _dialog_lock.acquire(blocking=False):
        raise Problem("已有文件选择窗口，请先完成或取消该选择。", 409)
    try:
        return _windows_dialog(kind, initial_directory(initial_path, kind))
    except OSError as exc:
        raise Problem("无法打开 Windows 选择窗口，请重试或手动填写路径。") from exc
    finally:
        _dialog_lock.release()


def _guid(value: str):
    """按 Windows GUID 的小端布局构造 COM 接口标识。"""
    return (ctypes.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)


def _check(result: int) -> None:
    """将失败 HRESULT 转换为可由上层统一处理的系统异常。"""
    if result < 0:
        raise OSError(f"Windows dialog HRESULT 0x{result & 0xFFFFFFFF:08X}")


def _call(pointer, index, types=(), *args):
    """调用 COM 虚表方法，显式声明指针类型以兼容 64 位 Windows。"""
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(table[index])
    return method(pointer, *args)


def _windows_dialog(kind: str, directory: Path) -> str | None:
    """使用 IFileOpenDialog 展示现代资源管理器界面，并在原线程释放所有 COM 资源。"""
    ole = ctypes.WinDLL("ole32")
    shell = ctypes.WinDLL("shell32")
    user = ctypes.WinDLL("user32", use_last_error=True)
    pointer, uint, wide = ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p
    ole.CoInitializeEx.argtypes = [pointer, uint]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoCreateInstance.argtypes = [pointer, pointer, uint, pointer, ctypes.POINTER(pointer)]
    ole.CoCreateInstance.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [pointer]
    ole.CoTaskMemFree.restype = None
    shell.SHCreateItemFromParsingName.argtypes = [wide, pointer, pointer, ctypes.POINTER(pointer)]
    shell.SHCreateItemFromParsingName.restype = ctypes.c_long
    user.CreateWindowExW.argtypes = [
        uint,
        wide,
        wide,
        uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        pointer,
        pointer,
        pointer,
        pointer,
    ]
    user.CreateWindowExW.restype = pointer
    user.DestroyWindow.argtypes = [pointer]
    user.DestroyWindow.restype = ctypes.c_int
    _check(ole.CoInitializeEx(None, 2))  # 当前 HTTP 工作线程使用 STA；Show 自带消息循环。
    dialog, folder, result, filename = pointer(), pointer(), pointer(), pointer()
    owner = None
    try:
        # 浏览器属于其他进程，不能直接作为所有者。当前线程的隐藏置顶所有者使
        # 用户主动打开的选择窗口显示在浏览器前，结束时连同所有者一起释放。
        owner = user.CreateWindowExW(
            0x88, "STATIC", "Resume Maker", 0x80000000, 0, 0, 0, 0, None, None, None, None
        )
        if not owner:
            raise ctypes.WinError(ctypes.get_last_error())
        _check(
            ole.CoCreateInstance(
                _guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"),
                None,
                1,
                _guid("D57C7288-D4AD-4768-BE02-9D969532D960"),
                ctypes.byref(dialog),
            )
        )
        # IFileDialog：SetOptions=9，强制文件系统路径、存在路径，且不更改进程工作目录。
        options = 0x40 | 0x800 | 0x8 | (0x20 if kind == "folder" else 0x1000)
        _check(_call(dialog, 9, (uint,), options))
        titles = {
            "folder": "Resume Maker · 选择文件夹",
            "docx": "Resume Maker · 选择 Word 文档",
            "executable": "Resume Maker · 选择 Codex 可执行文件",
        }
        _check(_call(dialog, 17, (wide,), titles[kind]))
        if kind != "folder":
            # COMDLG_FILTERSPEC 是两项宽字符串指针，数组在 Show 结束前保持存活。
            filters = (
                [("Word 文档 (*.docx)", "*.docx")]
                if kind == "docx"
                else [("可执行文件 (*.exe;*.cmd;*.bat)", "*.exe;*.cmd;*.bat"), ("所有文件", "*.*")]
            )
            specs = ((wide * 2) * len(filters))(*(tuple(pair) for pair in filters))
            _check(_call(dialog, 4, (uint, pointer), len(filters), ctypes.cast(specs, pointer)))
        shell_item = _guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")
        status = shell.SHCreateItemFromParsingName(
            str(directory), None, shell_item, ctypes.byref(folder)
        )
        if status >= 0:
            _check(_call(dialog, 12, (pointer,), folder))  # SetFolder
        status = _call(dialog, 3, (pointer,), owner)  # Show：继承所有者的置顶层级。
        if status == _CANCELLED:
            return None
        _check(status)
        _check(_call(dialog, 20, (ctypes.POINTER(pointer),), ctypes.byref(result)))
        _check(
            _call(result, 5, (uint, ctypes.POINTER(pointer)), 0x80058000, ctypes.byref(filename))
        )
        return ctypes.wstring_at(filename)
    finally:
        if filename:
            ole.CoTaskMemFree(filename)
        for item in (result, folder, dialog):
            if item:
                _call(item, 2)  # IUnknown.Release
        if owner:
            user.DestroyWindow(owner)
        ole.CoUninitialize()
