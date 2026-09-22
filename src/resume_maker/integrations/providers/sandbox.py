"""创建脱敏材料和控制文件分离的临时目录并限制其他账户访问"""

import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from resume_maker.integrations.providers.base import ProviderError


def toml(value):
    """生成参数中的 TOML 值，所有字符串交给 JSON 转义而不经过 shell"""
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + "=" + toml(v) for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=False)


def native_executable(name):
    """Windows 使用原生程序以避免 npm 批处理重解析参数及引号"""
    found = shutil.which(name)
    if not found:
        raise ProviderError("找不到 Codex CLI，请检查可执行文件路径。")
    path = Path(found).resolve()
    if os.name != "nt" or path.suffix.lower() == ".exe":
        return str(path)
    package = path.parent / "node_modules/@openai/codex"
    candidates = [
        *package.glob("node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe"),
        *package.glob("vendor/*/codex/codex.exe"),
    ]
    if len(candidates) != 1:
        raise ProviderError("隔离运行需要原生 codex.exe，请在模型设置中指定该文件。")
    return str(candidates[0].resolve())


def windows_parent(path):
    """控制目录只允许当前账户和系统访问，权限继承到任务文件"""
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), 8)
    owner = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    token.Close()
    current = win32security.GetNamedSecurityInfo(
        str(path), win32security.SE_FILE_OBJECT, win32security.OWNER_SECURITY_INFORMATION
    ).GetSecurityDescriptorOwner()
    if current != owner:
        raise ProviderError("沙箱父目录不属于当前账户，已停止使用该目录。")
    acl = win32security.ACL()
    for sid in (
        owner,
        win32security.ConvertStringSidToSid("S-1-5-18"),
        win32security.ConvertStringSidToSid("S-1-5-32-544"),
    ):
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 3, 0x1F01FF, sid)
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )


@contextmanager
def workspace():
    """在不含用户名的目录生成独立副本，清理前再次核验归属及路径"""
    base = (
        Path(os.environ.get("SystemDrive", "C:") + "/ResumeMakerSandbox")
        if os.name == "nt"
        else Path("/tmp/resume-maker-sandbox")
    )
    try:
        base.mkdir(mode=0o700, exist_ok=True)
        if base.is_symlink() or base.resolve() != base.absolute():
            raise ProviderError("沙箱根目录不能是链接，请检查 ResumeMakerSandbox 目录。")
        if os.name == "nt":
            windows_parent(base)
        root = Path(tempfile.mkdtemp(prefix="task-", dir=base))
        if os.name == "nt":
            windows_parent(root)
    except OSError as exc:
        raise ProviderError("无法创建隔离目录，请检查沙箱目录的写入权限。") from exc
    try:
        (root / "materials").mkdir()
        (root / "control").mkdir()
        yield root
    finally:
        if (
            root.resolve().parent == base.resolve()
            and root.name.startswith("task-")
            and not root.is_symlink()
        ):
            for attempt in range(20):
                try:
                    shutil.rmtree(root)
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.1)


def arguments(values):
    """逐项构造原生参数，不将任何配置拼接为可执行命令"""
    return [part for key, value in values.items() for part in ("-c", key + "=" + toml(value))]


def materials(root, prompt, schema):
    """保存脱敏文字及契约，把源码正文拆为可搜索的普通文本文件"""
    work = root / "materials"
    head, sep, tail = prompt.rpartition("\n")
    try:
        context = json.loads(tail)
    except ValueError:
        context = None
    if isinstance(context, dict):
        files = context.get("source_materials", {}).get("files", [])
        for index, item in enumerate(files):
            filename = f"source-{index + 1:04}.txt"
            (work / filename).write_text(item.pop("text"), encoding="utf-8", newline="")
            item["material_file"] = filename
        prompt = head + sep + json.dumps(context, ensure_ascii=False)
    (work / "context.txt").write_text(prompt, encoding="utf-8", newline="")
    (work / "schema.json").write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
    return prompt
