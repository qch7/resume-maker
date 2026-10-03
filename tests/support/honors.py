"""合成证书和荣誉任务等待"""

import time
from io import BytesIO

import pymupdf
import pytest
from PIL import Image


def certificate_bytes(kind="png", pages=1):
    """生成和用户资料无关的真实图片或多页 PDF，用于解码和预览验证"""
    if kind == "pdf":
        with pymupdf.open() as document:
            for index in range(pages):
                page = document.new_page(width=400, height=280)
                page.insert_text((30, 80), f"Demo Award {index + 1}")
            return document.tobytes()
    buffer = BytesIO()
    Image.new("RGB", (600, 400), "white").save(buffer, kind.upper())
    return buffer.getvalue()


def wait_honor(client, identifier, status="review"):
    """给 CI 的 OCR 冷启动留出余量，异常终态或超时包含最后一份资料"""
    deadline = time.monotonic() + 30
    while True:
        item = next(item for item in client.get("/api/honors").json() if item["id"] == identifier)
        if item["status"] == status:
            return item
        if item["status"] not in {"queued", "running"} or time.monotonic() >= deadline:
            pytest.fail(f"荣誉未到达 {status}: {item}")
        time.sleep(0.05)
