"""持久记录的公开编码和标识规则，不依赖具体数据库"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def now() -> str:
    """返回毫秒精度的 UTC 时间，供持久化记录和排序统一使用"""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def uid() -> str:
    """生成不依赖数据库自增序列的唯一记录标识"""
    return str(uuid4())


def dump(value: Any) -> str:
    """将数据编码为紧凑 UTF-8 JSON，保留中文并稳定比较草稿内容"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def unpack(row) -> dict | None:
    """把存储行转成字典，解码以 _json 结尾的列并去掉后缀"""
    if row is None:
        return None
    return {
        k.removesuffix("_json"): json.loads(v) if k.endswith("_json") and v else v
        for k, v in dict(row).items()
    }
