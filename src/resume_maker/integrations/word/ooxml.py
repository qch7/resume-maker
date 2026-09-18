"""WordprocessingML 的共享命名空间和标签构造"""

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def w(name: str) -> str:
    """构造 WordprocessingML 命名空间中的完整 XML 标签名"""
    return f"{{{NS['w']}}}{name}"
