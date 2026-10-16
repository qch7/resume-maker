"""只调整输出副本的正文及段落，不修改模板、姓名抬头或经历事实"""

from io import BytesIO
from zipfile import ZipFile

from lxml import etree

from resume_maker.domain.page_layout import layout_options
from resume_maker.infrastructure.filesystem import replace_file
from resume_maker.integrations.word.item_layout import BREAK, ITEM, apply_items
from resume_maker.integrations.word.ooxml import NS, w


def property_child(parent, name):
    """取得或创建单个属性，不替换其余格式"""
    found = parent.find(w(name))
    if found is None:
        found = etree.Element(w(name))
        if name == "rPr":
            parent.insert(0, found)
        else:
            parent.append(found)
    return found


def half_points(node, default):
    """缺少或无效字号时沿用上级格式，不从异常模板数值推断正文"""
    if node is None:
        return default
    try:
        value = float(node.get(w("val"), ""))
        return value if 0 < value <= 800 else default
    except ValueError:
        return default


def apply_page_layout(output, extensions):
    """完整保留压缩包其他部件，字号及间距只作用于正文大小的段落"""
    options = layout_options(extensions)
    global_layout = not all(
        value is None for value in (options.font_size, options.space_after, options.line_spacing)
    )
    with ZipFile(output) as archive:
        entries = [(entry, archive.read(entry.filename)) for entry in archive.infolist()]
    if (
        not global_layout
        and not options.auto_fit
        and not options.item_styles.types
        and not options.item_styles.items
        and not any(
            b"urn:resume-maker:item-layout" in data
            for entry, data in entries
            if entry.filename.endswith(".xml")
        )
    ):
        return
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    files = dict((entry.filename, data) for entry, data in entries)
    document = etree.fromstring(files["word/document.xml"], parser)
    styles = (
        etree.fromstring(files["word/styles.xml"], parser) if "word/styles.xml" in files else None
    )
    definitions = (
        {style.get(w("styleId")): style for style in styles.findall(w("style"))}
        if styles is not None
        else {}
    )
    base_size = (
        half_points(styles.find("w:docDefaults/w:rPrDefault/w:rPr/w:sz", NS), 22)
        if styles is not None
        else 22
    )

    def style_size(identifier, fallback, visited=None):
        """解析样式继承链，保留通过父样式设置的大标题字号"""
        visited = set() if visited is None else visited
        if identifier not in definitions or identifier in visited:
            return fallback
        visited.add(identifier)
        definition = definitions[identifier]
        parent = definition.find(w("basedOn"))
        inherited = (
            style_size(parent.get(w("val")), fallback, visited) if parent is not None else fallback
        )
        return half_points(definition.find("w:rPr/w:sz", NS), inherited)

    for paragraph in document.iter(w("p")):
        if not global_layout:
            break
        style = paragraph.find("w:pPr/w:pStyle", NS)
        default = style_size(style.get(w("val")) if style is not None else "Normal", base_size)
        default = half_points(paragraph.find("w:pPr/w:rPr/w:sz", NS), default)
        runs = [
            run
            for run in paragraph.iter(w("r"))
            if next(run.iterancestors(w("p")), None) is paragraph
        ]
        body = []
        for run in runs:
            if not run.findall(w("t")):
                continue
            size = run.find("w:rPr/w:sz", NS)
            character = run.find("w:rPr/w:rStyle", NS)
            inherited = (
                style_size(character.get(w("val")), default) if character is not None else default
            )
            actual = half_points(size, inherited)
            if actual > 24:
                continue
            body.append(run)
            if options.font_size is not None:
                props = property_child(run, "rPr")
                for key in ("sz", "szCs"):
                    property_child(props, key).set(w("val"), str(round(options.font_size * 2)))
        if not body:
            continue
        properties = paragraph.find(w("pPr"))
        if properties is None:
            properties = etree.Element(w("pPr"))
            paragraph.insert(0, properties)
        spacing = property_child(properties, "spacing")
        if options.space_after is not None:
            spacing.set(w("after"), str(round(options.space_after * 20)))
            if float(spacing.get(w("before"), "0")) <= 180:
                spacing.set(w("before"), str(round(options.space_after * 20)))
        if options.line_spacing is not None:
            spacing.set(w("line"), str(round(options.line_spacing * 240)))
            spacing.set(w("lineRule"), "auto")
    for name, data in list(files.items()):
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        root = document if name == "word/document.xml" else etree.fromstring(data, parser)
        if root.tag not in {w(tag) for tag in ("document", "hdr", "ftr", "footnotes", "endnotes")}:
            continue
        marked = any(ITEM in node.attrib or BREAK in node.attrib for node in root.iter())
        if (
            not marked
            and not options.auto_fit
            and not (name == "word/document.xml" and global_layout)
        ):
            continue
        apply_items(root, styles, options)
        files[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    if isinstance(output, BytesIO):
        temporary = BytesIO()
        with ZipFile(temporary, "w") as archive:
            for entry, _ in entries:
                archive.writestr(entry, files[entry.filename])
        output.seek(0)
        output.truncate()
        output.write(temporary.getvalue())
        return
    temporary = output.with_name("layout-" + output.name)
    try:
        with ZipFile(temporary, "w") as archive:
            for entry, _ in entries:
                archive.writestr(entry, files[entry.filename])
        replace_file(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def inline_honor(entry, section, enabled):
    """仅把明确的荣誉条目排成紧凑行，所有可见字段仍完整保留"""
    honor = (
        bool(entry.source and entry.source.provider == "ext.honors/library")
        or entry.id.startswith("honor:")
        or section.id == "honors"
        or any(label in section.title for label in ("荣誉", "获奖", "证书"))
    )
    if not enabled or not honor:
        return None
    return " · ".join(
        value.replace("\n", "；")
        for value in [
            entry.title,
            entry.subtitle,
            entry.period,
            *(f"{field.label}：{field.value}" for field in entry.custom_fields),
            entry.details,
        ]
        if value
    )
