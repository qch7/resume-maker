"""公开服务可标记装配和内部快照入口，避免重复记录一次用户操作"""


def internal(function):
    """纯装配和调用方已有轨迹的读取入口不产生独立业务日志"""
    function.__activity_internal__ = True
    return function
