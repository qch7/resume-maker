"""用合成中英文证书比较本地 OCR 分辨率、字段命中、耗时和峰值内存"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from resume_maker.integrations import local_ocr

FIELDS = [
    "张明远",
    "全国大学生软件设计竞赛",
    "一等奖",
    "2026年6月18日",
    "13800138000",
    "AB202600168",
    "student@example.com",
]


def sample(font, kind):
    """生成没有真实个人信息的清晰、小字及轻微倾斜扫描样本"""
    image = Image.new("RGB", (1600, 2260), "white")
    draw = ImageDraw.Draw(image)
    draw.text((480, 140), "荣誉证书", font=ImageFont.truetype(font, 80), fill="black")
    size = {"small": 24, "tiny": 14}.get(kind, 46)
    labels = ["姓名：", "项目：", "奖项：", "日期：", "电话：", "证书编号：", "邮箱："]
    for i, (label, value) in enumerate(zip(labels, FIELDS, strict=True)):
        draw.text(
            (150, 420 + 160 * i), label + value, font=ImageFont.truetype(font, size), fill="black"
        )
    if kind == "scan":
        image = image.rotate(2, resample=Image.Resampling.BICUBIC, fillcolor="white")
        image = image.filter(ImageFilter.GaussianBlur(0.6))
    if kind == "upside-down":
        image = image.rotate(180)
    return image


def measure(font, mode):
    """独立进程统计冷启动、页面耗时及进程峰值 RSS，置信度不作为准确率"""
    local_ocr.BASE_SIDE = {"fast": 960, "balanced": 960, "high": 2000}[mode]
    process = psutil.Process()
    peak, stopped = [process.memory_info().rss], threading.Event()

    def monitor():
        """采样本进程内存，包含模型、图片和 Python 运行时"""
        while not stopped.wait(0.02):
            peak[0] = max(peak[0], process.memory_info().rss)

    worker = threading.Thread(target=monitor)
    worker.start()
    started = time.perf_counter()
    local_ocr.engine()
    cold = time.perf_counter() - started
    rows = []
    try:
        for kind in ("clean", "small", "tiny", "scan", "upside-down"):
            image = sample(font, kind)
            started = time.perf_counter()
            result = local_ocr.recognize(image, threading.Event(), adaptive=mode == "balanced")
            elapsed = time.perf_counter() - started
            text = "".join(row["text"].replace(" ", "") for row in result["blocks"])
            matches = [value for value in FIELDS if value in text]
            rows.append(
                {
                    "sample": kind,
                    "seconds": round(elapsed, 3),
                    "field_matches": len(matches),
                    "fields": len(FIELDS),
                    "missing": [value for value in FIELDS if value not in matches],
                    "method": result["method"],
                }
            )
    finally:
        stopped.set()
        worker.join()
    return {
        "mode": mode,
        "cold_seconds": round(cold, 3),
        "peak_rss_mib": round(peak[0] / 1024**2, 1),
        "results": rows,
    }


def main():
    """使用指定中文字体运行可复现对比，不访问网络或调用大模型"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", default="C:/Windows/Fonts/msyh.ttc")
    parser.add_argument("--mode", choices=("fast", "balanced", "high"))
    args = parser.parse_args()
    if not Path(args.font).is_file():
        parser.error("请通过 --font 指定本机中文字体")
    if args.mode:
        result = measure(args.font, args.mode)
    else:
        result = []
        for mode in ("fast", "balanced", "high"):
            run = subprocess.run(
                [sys.executable, __file__, "--font", args.font, "--mode", mode],
                env={**os.environ, "PYTHONUTF8": "1"},
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            result.append(json.loads(run.stdout))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
