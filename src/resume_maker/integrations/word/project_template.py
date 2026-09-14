"""项目区模板的统一填充器，预览和正式导出保留相同版式。"""

from copy import deepcopy

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.integrations.word.ooxml import (
    NS,
    TAG,
    make_body,
    make_title,
    read_document,
    rewrite_archive,
    text_of,
    w,
)


def fill_project_template(source, output, projects):
    """仅替换已标记的项目区，沿用模板字体、样本样式与分节设置。"""
    if not projects:
        raise Problem("请至少选择一个项目经历。")
    root = read_document(source)
    controls = root.xpath("//w:sdt[w:sdtPr/w:tag[@w:val=$tag]]", namespaces=NS, tag=TAG)
    if len(controls) != 1:
        raise Problem("模板缺少唯一项目经历插入位置，请重新导入。")
    content = controls[0].find("w:sdtContent", NS)
    old = list(content)
    title_sample = next((p for p in old if text_of(p).strip()), old[0])
    body_sample = next((p for p in old if "项目描述" in text_of(p)), title_sample)
    sections = [deepcopy(s) for s in content.xpath(".//w:sectPr", namespaces=NS)]
    for child in list(content):
        content.remove(child)
    for index, item in enumerate(projects):
        value = item["content"]
        content.append(make_title(value, title_sample, first=index == 0))
        if value["stack"]:
            content.append(make_body("技术栈", "、".join(value["stack"]), body_sample, keep=True))
        if value["role"]:
            content.append(make_body("担任角色", value["role"], body_sample, keep=True))
        if value["description"]:
            content.append(make_body("项目描述", value["description"], body_sample, keep=True))
        by_id = {h["id"]: h for h in value["highlights"]}
        for point_id in item["highlight_ids"]:
            if point_id not in by_id:
                raise Problem("组合引用了无效亮点，请重新保存组合。")
            highlight = by_id[point_id]
            content.append(make_body(highlight["title"], highlight["text"], body_sample))
    for section in sections:
        paragraph = etree.SubElement(content, w("p"))
        etree.SubElement(paragraph, w("pPr")).append(section)
    rewrite_archive(source, output, root)
