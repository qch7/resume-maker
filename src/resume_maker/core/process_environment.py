"""按子进程职责声明环境继承范围，供应商凭据只进入明确选定的连接"""

import os
from enum import StrEnum

from resume_maker.core.environment import LAUNCH_VARIABLES, PROVIDER_KEY

BASE_SYSTEM = frozenset({"SYSTEMROOT", "WINDIR", "PATH"})
CANDIDATE_SYSTEM = BASE_SYSTEM | {
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOME",
    "LOCALAPPDATA",
}
DESKTOP_SYSTEM = CANDIDATE_SYSTEM | {
    "SYSTEMDRIVE",
    "COMSPEC",
    "APPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)",
    "USERNAME",
    "USERDOMAIN",
    "SESSIONNAME",
}
MODEL_SYSTEM = DESKTOP_SYSTEM | {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}
DESKTOP_SESSION = frozenset(
    {
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "LANG",
        "LC_ALL",
    }
)


class EnvironmentPolicy(StrEnum):
    """正式宿主保留连接输入，其余职责只继承明确的系统键"""

    HOST = "host"
    CANDIDATE = "candidate"
    WORKER = "worker"
    MODEL = "model"
    DESKTOP = "desktop"


ALLOWLISTS = {
    EnvironmentPolicy.CANDIDATE: CANDIDATE_SYSTEM,
    EnvironmentPolicy.WORKER: BASE_SYSTEM,
    EnvironmentPolicy.MODEL: MODEL_SYSTEM,
    EnvironmentPolicy.DESKTOP: DESKTOP_SYSTEM | DESKTOP_SESSION,
}


def process_environment(policy: EnvironmentPolicy, environment=None):
    """大小写无关地筛选键，返回副本且不修改父进程环境"""
    source = os.environ if environment is None else environment
    if policy == EnvironmentPolicy.HOST:
        blocked = LAUNCH_VARIABLES.keys() | {PROVIDER_KEY}
        return {key: value for key, value in source.items() if key.upper() not in blocked}
    allowed = ALLOWLISTS[policy]
    return {key: value for key, value in source.items() if key.upper() in allowed}
