"""凭标题、留白和后续独立标题识别侧栏，避免把两条文字流拆成交错的表格行"""

from itertools import combinations


def heading_style(line):
    """根据粗体或颜色提取标题样式"""
    spans = [span for span in line.spans if span.text.strip()]
    if not spans:
        return None
    span = max(spans, key=lambda item: len(item.text))
    return (round(span.size, 1), span.color, span.flags & 16) if span.flags & 16 else None


def sidebar_band(column, page):
    """要求同行双标题、连续竖向留白和单侧后续标题，普通表头或有横向网格的表格不拆"""
    lines = list(column.blocks)
    if any(not hasattr(line, "spans") or not line.is_horizontal_text for line in lines):
        return None
    headings = [line for line in lines if heading_style(line)]
    for first, second in combinations(headings, 2):
        left, right = sorted((first, second), key=lambda line: line.bbox.x0)
        style = heading_style(left)
        if (
            style != heading_style(right)
            or abs(left.bbox.y0 - right.bbox.y0) > 2
            or right.bbox.x0 - left.bbox.x1 < style[0] * 2
        ):
            continue
        top = min(left.bbox.y0, right.bbox.y0)
        split = right.bbox.x0 - style[0]
        following = [line for line in lines if line.bbox.y0 >= top - 1]
        crossing = [line.bbox.y0 for line in following if line.bbox.x0 < split < line.bbox.x1]
        bottom = min(crossing, default=column.bbox.y1 + 1)
        band = [line for line in following if line.bbox.y1 <= bottom]
        groups = [
            [line for line in band if (line.bbox.x0 >= split) == side] for side in (False, True)
        ]
        if min(map(len, groups)) < 3:
            continue
        gutter = min(line.bbox.x0 for line in groups[1]) - max(line.bbox.x1 for line in groups[0])
        if gutter < style[0] * 2:
            continue
        # 表格的一排表头不足以证明独立栏目：还需一侧出现新标题，另一侧仍有普通正文
        independent = any(
            heading_style(line) == style
            and line.bbox.y0 > top + style[0] * 2
            and any(
                heading_style(other) != style and abs(other.bbox.y0 - line.bbox.y0) < style[0]
                for other in groups[1 - side]
            )
            for side, group in enumerate(groups)
            for line in group
        )
        if not independent:
            continue
        if any(
            drawing.get("color") is not None
            and drawing["rect"].x0 < split - style[0]
            and drawing["rect"].x1 > split + style[0]
            and top - 2 <= drawing["rect"].y0 <= bottom
            and drawing["rect"].height < 2
            for drawing in page.get_drawings()
        ):
            continue
        return top, bottom, split, groups
    return None


def parse_sidebar(column, page, settings):
    """将有独立栏目证据的文字流放入两个可增长单元格，其余区域保持原解析规则"""
    from pdf2docx.layout.Column import Column
    from pdf2docx.table.TableBlock import TableBlock

    band = sidebar_band(column, page)
    if band is None:
        return False
    top, bottom, split, groups = band
    lines = list(column.blocks)
    edges = (column.bbox.x0, split, column.bbox.x1)
    cells = []
    for index, group in enumerate(groups):
        box = (edges[index], top, edges[index + 1], max(line.bbox.y1 for line in group))
        region = Column(box)
        region.blocks.reset(group)
        region.assign_shapes(list(column.shapes))
        region.parse(**{**settings, "parse_stream_table": False})
        cells.append({**region.store(), "border_width": (0, 0, 0, 0)})
    height = max(cell["bbox"][3] for cell in cells) - top
    for cell in cells:
        cell["bbox"] = (*cell["bbox"][:3], top + height)
    table = TableBlock({"rows": [{"height": height, "cells": cells}]})
    table.independent_columns = True
    output = []
    for before in (True, False):
        remaining = (
            [line for line in lines if line.bbox.y0 < top - 1]
            if before
            else [
                line
                for line in lines
                if line not in groups[0] and line not in groups[1] and line.bbox.y0 >= top - 1
            ]
        )
        if remaining:
            region = Column(
                (
                    column.bbox.x0,
                    min(line.bbox.y0 for line in remaining),
                    column.bbox.x1,
                    max(line.bbox.y1 for line in remaining),
                )
            )
            region.blocks.reset(remaining)
            region.assign_shapes(list(column.shapes))
            region.parse(**settings)
            if before:
                table.before_space = max(0, top - region.bbox.y1)
            elif region.blocks:
                region.blocks[0].before_space += max(0, region.bbox.y0 - top - height)
            output.extend(region.blocks)
        if before:
            output.append(table)
    column.blocks.reset(output)
    return True
