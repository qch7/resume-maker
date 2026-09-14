"""在模板副本中去除编辑批注，正文与脚注尾注保留给字段识别。"""

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w

COMMENT_RELATIONS = {"comments", "commentsExtended", "commentsIds", "commentsExtensible", "people"}
COMMENT_MARKS = {w("commentRangeStart"), w("commentRangeEnd"), w("commentReference")}
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def prepare_parts(files: dict[str, bytes]) -> list[str]:
    """副本中选择 Word 的实际绘图表示并清除批注，不改动原文件。"""
    removed = {
        name
        for name in files
        if name.startswith("word/comments")
        or name == "word/people.xml"
        or name.startswith("word/_rels/comments")
    }
    changed = False
    for name in list(files):
        if name in removed:
            del files[name]
            continue
        if not (
            name.endswith(".rels")
            or name == "[Content_Types].xml"
            or (name.startswith("word/") and name.endswith(".xml"))
        ):
            continue
        root = etree.fromstring(
            files[name], etree.XMLParser(resolve_entities=False, no_network=True)
        )
        dirty = False
        for alternate in list(root.iter(f"{{{MC}}}AlternateContent")):
            parent = alternate.getparent()
            if parent is None:
                continue
            choice = next(
                (
                    child
                    for child in alternate
                    if child.tag == f"{{{MC}}}Choice"
                    and set(child.get("Requires", "").split())
                    <= {"wps", "wpg", "w14", "w15", "w16"}
                ),
                None,
            )
            if choice is None:
                choice = alternate.find(f"{{{MC}}}Fallback")
            if choice is not None:
                position = parent.index(alternate)
                for child in list(choice):
                    parent.insert(position, child)
                    position += 1
                parent.remove(alternate)
                dirty = True
        for node in list(root.iter()):
            if node.getparent() is None:
                continue
            if (
                node.tag in COMMENT_MARKS
                or (
                    name.endswith(".rels")
                    and node.get("Type", "").rsplit("/", 1)[-1] in COMMENT_RELATIONS
                )
                or (
                    name == "[Content_Types].xml"
                    and node.get("PartName", "").lstrip("/") in removed
                )
            ):
                node.getparent().remove(node)
                dirty = True
                changed = True
        if dirty:
            files[name] = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
    return ["已在模板副本中忽略编辑批注，原 Word 文件保持不变。"] if removed or changed else []


def system_note(node) -> bool:
    """只跳过没有文字或图片的系统分隔线，用户编写的脚注尾注仍参与识别。"""
    return (
        node.tag in {w("footnote"), w("endnote")}
        and node.get(w("type")) in {"separator", "continuationSeparator"}
        and not node.xpath(".//w:t | .//w:drawing | .//w:pict | .//w:object", namespaces=NS)
    )
