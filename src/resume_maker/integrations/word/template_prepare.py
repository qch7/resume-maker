"""在模板副本中整理动态域、修订、绑定、绘图与批注，保留当前文字供识别。"""

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.template_anchors import separate_anchors
from resume_maker.integrations.word.template_fields import freeze_fields

COMMENT_RELATIONS = {"comments", "commentsExtended", "commentsIds", "commentsExtensible", "people"}
COMMENT_MARKS = {w("commentRangeStart"), w("commentRangeEnd"), w("commentReference")}
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def normalize_document_kind(files):
    """将 DOCM/DOTX 等包规范为不含宏的 DOCX 副本，避免后续扩展名与内容类型不匹配。"""
    changed = False
    for name in list(files):
        if name.startswith(("word/vba", "word/_rels/vba")):
            del files[name]
            changed = True
            continue
        if name != "[Content_Types].xml" and not name.endswith(".rels"):
            continue
        root = etree.fromstring(
            files[name], etree.XMLParser(resolve_entities=False, no_network=True)
        )
        dirty = False
        for node in list(root):
            if (
                node.get("Type", "").rsplit("/", 1)[-1].startswith("vba")
                or "vba" in node.get("ContentType", "").lower()
            ):
                root.remove(node)
                dirty = True
            elif node.get("PartName", "").lstrip("/") == "word/document.xml":
                content_type = (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document.main+xml"
                )
                if node.get("ContentType") != content_type:
                    node.set("ContentType", content_type)
                    dirty = True
        if dirty:
            files[name] = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
            changed = True
    return changed


def prepare_parts(files: dict[str, bytes]) -> list[str]:
    """副本中选择实际绘图、冻结动态域、接受修订和解除绑定，不改动原文件。"""
    normalized_kind = normalize_document_kind(files)
    removed = {
        name
        for name in files
        if name.startswith("word/comments")
        or name == "word/people.xml"
        or name.startswith("word/_rels/comments")
    }
    changed = False
    fields, revisions, bindings, missing_notes = set(), 0, 0, 0
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
        dirty |= separate_anchors(root)
        # 接受当前修订：保留插入与移入，移除已删除内容及旧属性快照。
        for node in list(root.iter()):
            if node.getparent() is None:
                continue
            if node.tag in {w("ins"), w("moveTo")}:
                parent, position = node.getparent(), node.getparent().index(node)
                for child in list(node):
                    parent.insert(position, child)
                    position += 1
                parent.remove(node)
                revisions += 1
                dirty = True
            elif node.tag in {w("del"), w("moveFrom")} or (
                isinstance(node.tag, str)
                and node.tag.startswith(f"{{{NS['w']}}}")
                and (
                    etree.QName(node).localname.endswith("PrChange")
                    or "Range" in etree.QName(node).localname
                    and "move" in etree.QName(node).localname
                )
            ):
                node.getparent().remove(node)
                revisions += 1
                dirty = True
            elif node.tag in {
                w("dataBinding"),
                w("lock"),
                w("updateFields"),
                w("trackRevisions"),
                w("documentProtection"),
                w("writeProtection"),
            }:
                node.getparent().remove(node)
                bindings += 1
                dirty = True
        converted = freeze_fields(root)
        fields.update(converted)
        dirty |= bool(converted)
        for kind in ("footnote", "endnote"):
            note_data = files.get(f"word/{kind}s.xml")
            notes = (
                etree.fromstring(
                    note_data, etree.XMLParser(resolve_entities=False, no_network=True)
                )
                if note_data
                else []
            )
            identifiers = {node.get(w("id")) for node in notes}
            for node in list(root.iter(w(f"{kind}Reference"))):
                if node.get(w("id")) not in identifiers:
                    node.getparent().remove(node)
                    missing_notes += 1
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
    notices = ["已在模板副本中忽略编辑批注，原 Word 文件保持不变。"] if removed or changed else []
    if normalized_kind:
        notices.append("已转换为标准 DOCX 副本并清理宏组件，保留文档内容与样式。")
    if fields:
        notices.append(
            "已将动态域（"
            + "、".join(sorted(fields))
            + "）转为普通文字，保留已有显示内容和样式；无显示内容的位置可继续填入资料。"
        )
    if revisions:
        notices.append("已在模板副本中接受修订，保留当前版本内容。")
    if bindings:
        notices.append("已解除内容绑定与编辑锁定，保留当前显示内容。")
    if missing_notes:
        notices.append("已清理失效的脚注或尾注引用；源文件中没有这些引用对应的正文。")
    return notices


def system_note(node) -> bool:
    """只跳过没有文字或图片的系统分隔线，用户编写的脚注尾注仍参与识别。"""
    return (
        node.tag in {w("footnote"), w("endnote")}
        and node.get(w("type")) in {"separator", "continuationSeparator"}
        and not node.xpath(".//w:t | .//w:drawing | .//w:pict | .//w:object", namespaces=NS)
    )
