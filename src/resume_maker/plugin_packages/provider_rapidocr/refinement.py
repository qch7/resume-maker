"""按实际文字区域选择复核结果，拆行、合行不以文字框数量判优"""

import math
import unicodedata
from collections import defaultdict
from itertools import pairwise

from resume_maker.integrations.ocr_support import REVIEW_SCORE, check_cancelled

CONFIDENCE_TOLERANCE = 0.03
MIN_COVERAGE = 0.8
VERTICAL_BANDS = 64


def blocks_from_rows(rows, size):
    """两次识别统一到相对坐标，忽略空文字及无效边界"""
    width, height = size
    blocks = []
    for points, text, score, *_ in rows or []:
        if not text.strip():
            continue
        xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]
        if not all(math.isfinite(v) for v in [*xs, *ys, score]):
            continue
        box = [
            max(0, min(xs) / width),
            max(0, min(ys) / height),
            min(1, max(xs) / width),
            min(1, max(ys) / height),
        ]
        if box[0] < box[2] and box[1] < box[3]:
            blocks.append({"text": text.strip(), "box": box, "confidence": round(float(score), 4)})
    return blocks


def intersection(left, right):
    """返回严格相交的矩形，相接边界不视作同一文字区域"""
    box = (
        max(left[0], right[0]),
        max(left[1], right[1]),
        min(left[2], right[2]),
        min(left[3], right[3]),
    )
    return box if box[0] < box[2] and box[1] < box[3] else None


def covered_area(rectangles):
    """按横向条带合并纵向区间，重叠复核框只能计入一次覆盖面积"""
    edges = sorted({x for box in rectangles for x in (box[0], box[2])})
    area = 0.0
    for left, right in pairwise(edges):
        intervals = sorted(
            (box[1], box[3]) for box in rectangles if box[0] <= left and box[2] >= right
        )
        height, end = 0.0, -1.0
        for top, bottom in intervals:
            height += max(0.0, bottom - max(top, end))
            end = max(end, bottom)
        area += (right - left) * height
    return area


class RegionIndex:
    """用纵向分桶缩小候选范围，避免逐行扫描另一轮的全部结果"""

    def __init__(self, blocks):
        """索引只用于本次复核，不持有模型或原始图片"""
        self.blocks, self.bands = blocks, defaultdict(list)
        for index, block in enumerate(blocks):
            for band in self.keys(block["box"]):
                self.bands[band].append(index)

    @staticmethod
    def keys(box):
        """跨分桶文字登记到覆盖的全部桶，边界候选随后精确过滤"""
        return range(int(box[1] * VERTICAL_BANDS), int(box[3] * VERTICAL_BANDS) + 1)

    def matches(self, box):
        """按原结果顺序返回有实际交集的文字框"""
        indices = {index for band in self.keys(box) for index in self.bands.get(band, ())}
        return [
            self.blocks[index]
            for index in sorted(indices)
            if intersection(box, self.blocks[index]["box"])
        ]


def normalized_text(text):
    """统一全角、空白和大小写后比较拆行、合行中的已有文字"""
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def preserves_region(block, candidates):
    """复核须覆盖原区域且不降低本行可信度，高分旧文字还需保持一致"""
    box = block["box"]
    # 邻行即使文字很长也不能抬高本行的可信度，只有合格区域计入覆盖
    candidates = [
        row for row in candidates if row["confidence"] >= block["confidence"] - CONFIDENCE_TOLERANCE
    ]
    rectangles = [intersection(box, row["box"]) for row in candidates]
    area = (box[2] - box[0]) * (box[3] - box[1])
    if covered_area(rectangles) < MIN_COVERAGE * area:
        return False
    if block["confidence"] < REVIEW_SCORE:
        return True
    previous = normalized_text(block["text"])
    ordered = sorted(candidates, key=lambda row: (round(row["box"][1], 2), row["box"][0]))
    current = normalized_text("".join(row["text"] for row in ordered))
    # 可靠文字必须完整保留，空间覆盖阈值不能变成允许丢失数字或姓名的比例
    return previous in current


def refine_blocks(previous, alternate, cancelled):
    """全部旧行通过检查才替换整页，否则保留旧文字并补入不相交的高分新区域"""
    if not previous or not alternate:
        return alternate or previous
    index = RegionIndex(alternate)
    for block in previous:
        check_cancelled(cancelled)
        candidates = index.matches(block["box"])
        if not candidates or not preserves_region(block, candidates):
            break
    else:
        return alternate
    index = RegionIndex(previous)
    result = list(previous)
    for block in alternate:
        check_cancelled(cancelled)
        if block["confidence"] >= REVIEW_SCORE and not index.matches(block["box"]):
            result.append(block)
    return sorted(result, key=lambda row: (round(row["box"][1], 2), row["box"][0]))
