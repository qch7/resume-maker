"""提取模板的稳定节点清单，校验精确引文、重复区域与完整覆盖。"""

import posixpath
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote
from zipfile import BadZipFile, ZipFile

from lxml import etree

from resume_maker.core.errors import Problem
from resume_maker.domain.resume import PersonalInfo
from resume_maker.domain.templates import TemplatePlan, TextBinding
from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.template_prepare import prepare_parts, system_note

NS = {
    **NS,
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
}
IMAGE_TAGS = {f"{{{NS['a']}}}blip", f"{{{NS['v']}}}imagedata"}
BLOCK_TAGS = {w("p"), w("tbl"), w("tr")}
NOTE_PARTS = {"word/footnotes.xml", "word/endnotes.xml"}
PERSONAL_TARGETS = {f"personal.{field}" for field in PersonalInfo.model_fields} - {
    "personal.hidden_fields",
    "personal.photo",
}
ENTRY_TARGETS = {
    "title",
    "subtitle",
    "period",
    "details",
    "role",
    "stack",
    "description",
    "highlights",
    "custom_fields",
}


def paragraph_texts(paragraph):
    """仅读取本段文字，文本框中的内层段落独立编号和替换。"""
    return [
        node
        for node in paragraph.iter(w("t"))
        if next(node.iterancestors(w("p")), None) is paragraph
    ]


def paragraph_text(paragraph) -> str:
    """合并可跨样式片段的段落文字，保持与 AI 引文定位一致。"""
    return "".join(node.text or "" for node in paragraph_texts(paragraph))


def image_container(node):
    """定位图片所属 Word 绘图，校验与删除共用同一个真实操作范围。"""
    return next(
        (parent for parent in node.iterancestors() if parent.tag in {w("drawing"), w("pict")}),
        node,
    )


def can_insert(paragraph) -> bool:
    """仅真正空白的段落能补入字段，含照片、文本框或域的无文字段落不是空位。"""
    if paragraph.tag != w("p") or paragraph_text(paragraph):
        return False
    for child in paragraph:
        if child.tag == w("pPr"):
            continue
        if child.tag != w("r") or any(node.tag not in {w("rPr"), w("t")} for node in child):
            return False
    return True


def quote_range(text: str, binding: TextBinding) -> tuple[int, int]:
    """定位指定次出现的精确引文，拒绝猜测或模糊匹配。"""
    if not binding.quote:
        if text or binding.occurrence != 1:
            raise Problem("空引文只能填入原本没有文字的段落，且出现次数必须为 1。")
        return 0, 0
    start = -1
    for _ in range(binding.occurrence):
        start = text.find(binding.quote, start + 1)
        if start < 0:
            raise Problem(f"找不到引文：{binding.node} · {binding.quote[:50]}")
    return start, start + len(binding.quote)


class TemplatePackage:
    """读取所有可排版文字部件，保留未修改的包资源与 XML 属性。"""

    def __init__(self, path: Path | BytesIO):
        """限制包大小并禁用 XML 外部实体，给结构和图片分配稳定标识。"""
        self.parts, self.nodes, self.locations, self.ids = {}, {}, {}, {}
        self.notices = []
        try:
            with ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > 100_000_000:
                    raise Problem("模板解压后超过 100 MB。")
                names = archive.namelist()
                if "word/document.xml" not in names or len(set(names)) != len(names):
                    raise Problem("文件不是有效的 DOCX 模板。")
                self.files = {name: archive.read(name) for name in names}
            self.notices = prepare_parts(self.files)
            for name in sorted(self.files):
                if name in NOTE_PARTS | {"word/document.xml"} or (
                    name.startswith(("word/header", "word/footer")) and name.endswith(".xml")
                ):
                    root = etree.fromstring(
                        self.files[name], etree.XMLParser(resolve_entities=False, no_network=True)
                    )
                    if name in NOTE_PARTS and all(system_note(child) for child in root):
                        continue
                    self.parts[name] = root
                    for node in root.iter():
                        if name in NOTE_PARTS and (
                            system_note(node)
                            or any(system_note(parent) for parent in node.iterancestors())
                        ):
                            continue
                        identifier = f"n{len(self.nodes) + 1}"
                        self.nodes[identifier] = node
                        self.ids[node] = identifier
                        self.locations[identifier] = name
        except (BadZipFile, etree.XMLSyntaxError, KeyError) as exc:
            raise Problem("文件不是有效的 Word DOCX 模板。") from exc

    def inventory(self) -> dict:
        """列出正文、表格、文本框、页眉页脚及图片，报告不能自动处理的对象。"""
        rows, warnings = [], []
        for identifier, node in self.nodes.items():
            if node.tag not in BLOCK_TAGS | IMAGE_TAGS:
                continue
            kind = "image" if node.tag in IMAGE_TAGS else etree.QName(node).localname
            text = paragraph_text(node) if kind == "p" else "".join(node.itertext())[:300]
            if kind == "image":
                text = "图片或照片"
                picture = next(
                    (
                        parent
                        for parent in node.iterancestors()
                        if parent.tag in {w("drawing"), w("pict")}
                    ),
                    None,
                )
                if picture is not None:
                    description = picture.xpath(
                        ".//*[local-name()='docPr']/@descr | .//*[local-name()='docPr']/@name"
                    )
                    dimensions = picture.xpath(".//*[local-name()='extent']")
                    if dimensions:
                        size = dimensions[0]
                        try:
                            width, height = int(size.get("cx", "0")), int(size.get("cy", "0"))
                            description.append(
                                f"约 {width / 360000:.1f} × {height / 360000:.1f} 厘米"
                            )
                        except ValueError:
                            pass
                    text += " · " + " · ".join(description)
            rows.append(
                {
                    "id": identifier,
                    "parent": self.ids.get(node.getparent(), ""),
                    "part": self.locations[identifier],
                    "kind": kind,
                    "text": text,
                    "can_insert": can_insert(node),
                    "ancestors": [
                        self.ids[parent]
                        for parent in node.iterancestors()
                        if parent.tag in BLOCK_TAGS
                    ],
                }
            )
        for root in self.parts.values():
            if root.xpath(".//w:object | .//w:altChunk | .//w:ins | .//w:del", namespaces=NS):
                warnings.append(
                    "模板包含嵌入对象或修订记录，请先在 Word 中转换为普通内容并接受修订。"
                )
            if root.xpath(".//w:dataBinding | .//a:t | .//*[local-name()='chart']", namespaces=NS):
                warnings.append("模板包含数据绑定、图表或绘图文字，请先转换为普通 Word 文字。")
            codes = root.xpath(".//w:instrText/text() | .//w:fldSimple/@w:instr", namespaces=NS)
            if any(code.strip().upper() not in {"PAGE", "NUMPAGES"} for code in codes):
                warnings.append("模板含动态域，请先在 Word 中将页码以外的域转换为普通文字。")
        for kind in ("footnote", "endnote"):
            note_root = self.parts.get(f"word/{kind}s.xml")
            note_ids = {node.get(w("id")) for node in note_root} if note_root is not None else set()
            if any(
                node.get(w("id")) not in note_ids
                for root in self.parts.values()
                for node in root.iter(w(f"{kind}Reference"))
            ):
                warnings.append("文档的脚注或尾注内容缺失，请在 Word 中修复引用后重试。")
        if not any(row["kind"] == "p" and row["text"].strip() for row in rows):
            warnings.append("没有可编辑文字，图片形式的简历须先转换为可编辑 DOCX。")
        if len(rows) > 2000 or sum(len(row["text"]) for row in rows) > 100000:
            raise Problem("模板内容过多，请只保留简历页面后再分析。")
        return {"nodes": rows, "warnings": list(dict.fromkeys(warnings)), "notices": self.notices}

    def node(self, identifier: str):
        """只解析清单中实际存在的节点，拒绝模型生成的路径或外部引用。"""
        if identifier not in self.nodes:
            raise Problem(f"模板节点不存在：{identifier}")
        return self.nodes[identifier]

    def image(self, identifier: str) -> bytes:
        """仅读取此模板内嵌图片供人工核对，不跟随外部链接或读取包外文件。"""
        node = self.node(identifier)
        if node.tag not in IMAGE_TAGS:
            raise Problem("该位置不是图片。", 404)
        part = self.locations[identifier]
        attribute = f"{{{NS['r']}}}{'embed' if node.tag.endswith('blip') else 'id'}"
        rel_path = relationship_part(part)
        root = etree.fromstring(
            self.files.get(rel_path, b"<Relationships/>"),
            etree.XMLParser(resolve_entities=False, no_network=True),
        )
        relation = next((item for item in root if item.get("Id") == node.get(attribute)), None)
        if relation is None or relation.get("TargetMode") == "External":
            raise Problem("图片不是有效内嵌资源，请在 Word 中检查。", 404)
        target = relationship_target(part, relation.get("Target", ""))
        if not target.startswith("word/media/") or target not in self.files:
            raise Problem("图片资源不存在。", 404)
        return self.files[target]

    def region(self, start: str, end: str) -> list:
        """重复区使用同一父节点的闭区间，支持段落、完整表格和表格行。"""
        first, last = self.node(start), self.node(end)
        parent = first.getparent()
        if parent is None or parent is not last.getparent():
            raise Problem("重复区域起止位置必须位于同一容器。")
        left, right = parent.index(first), parent.index(last)
        if left > right:
            raise Problem("重复区域起点不能晚于终点。")
        nodes = list(parent)[left : right + 1]
        if any(node.tag not in BLOCK_TAGS for node in nodes):
            raise Problem("重复区域只能包含段落、表格或表格行。")
        if any(
            section.find(w("type")) is None or section.find(w("type")).get(w("val")) != "continuous"
            for node in nodes
            for section in node.iter(w("sectPr"))
        ):
            raise Problem("重复区域跨越分页分节，请只选择同一连续排版中的条目。")
        return nodes

    def descendants(self, nodes: list) -> set[str]:
        """收集区域内全部节点标识，供嵌套冲突和覆盖检查使用。"""
        return {self.ids[child] for node in nodes for child in node.iter()}

    def validate_fields(self, fields: list[TextBinding], *, local: bool = False) -> set[str]:
        """核验目标字段、引文和重叠范围，防止替换相邻字段或跨区域写入。"""
        intervals = {}
        for binding in fields:
            node = self.node(binding.node)
            if node.tag != w("p"):
                raise Problem("文字映射必须指向段落。")
            if not binding.quote and not can_insert(node):
                raise Problem("空引文只能使用真正空白的段落，不能占用照片、文本框或其他内容。")
            valid = (
                binding.target in ENTRY_TARGETS
                if local
                else (
                    binding.target in PERSONAL_TARGETS
                    or binding.target.startswith("personal.custom:")
                    or binding.target.startswith("section-title:")
                )
            )
            if not valid:
                raise Problem(f"不支持的替换字段：{binding.target}")
            interval = quote_range(paragraph_text(node), binding)
            previous = intervals.setdefault(binding.node, [])
            if any(
                interval == (start, end) or (interval[0] < end and start < interval[1])
                for start, end in previous
            ):
                raise Problem(f"同一段落的映射引文重叠：{binding.node}")
            previous.append(interval)
        return set(intervals)

    def review(self, plan: TemplatePlan) -> dict:
        """逐项检查全部映射，单处错误不影响其他区域的覆盖统计和定位。"""
        inventory = self.inventory()
        errors = list(inventory["warnings"])
        issues = [{"message": message, "nodes": []} for message in errors]
        covered, occupied = set(), set()

        def report(message, identifiers):
            """记录可定位的问题，继续检查其他独立映射。"""
            errors.append(message)
            issues.append(
                {"message": message, "nodes": [i for i in identifiers if i in self.nodes]}
            )

        for identifiers in (plan.photos, plan.keep, plan.remove):
            if len(identifiers) != len(set(identifiers)):
                report("照片、保留项或删除项中存在重复位置。", identifiers)
        conflicts = set(plan.keep) & (set(plan.photos) | set(plan.remove))
        if conflicts:
            report("同一位置不能同时保留和替换或删除。", conflicts)
        # 已声明的区域即使需要修正，也不重复统计为尚未识别；错误仍会阻止导出。
        covered.update(field.node for field in plan.fields if field.node in self.nodes)
        try:
            self.validate_fields(plan.fields)
        except Problem as exc:
            report(str(exc), [field.node for field in plan.fields])
        for repeat in plan.repeats:
            try:
                region = self.region(repeat.start, repeat.end)
                ids = self.descendants(region)
                overlap = ids & (occupied | covered)
                covered |= ids
                occupied |= ids
                if overlap:
                    raise Problem("重复区域之间或与独立字段发生重叠。")
                sample = self.region(repeat.sample_start, repeat.sample_end)
                if any(node not in region for node in sample):
                    raise Problem("样式样本必须包含在重复区域内。")
                mapped = self.validate_fields(repeat.fields, local=True)
                if not mapped <= self.descendants(sample):
                    raise Problem("重复字段必须位于所选样式样本内。")
                sample_content = {
                    self.ids[p]
                    for node in sample
                    for p in node.iter(w("p"))
                    if paragraph_text(p).strip()
                }
                sample_content |= {
                    self.ids[child]
                    for node in sample
                    for child in node.iter()
                    if child.tag in IMAGE_TAGS
                }
                missing = sample_content - mapped - set(plan.keep)
                if missing:
                    report(
                        "重复样本含未映射文字或图片，请补充映射或确认固定标签。", sorted(missing)
                    )
            except Problem as exc:
                report(str(exc), [repeat.sample_start, repeat.start])
        for identifier in plan.photos:
            covered.add(identifier)
            try:
                if self.node(identifier).tag not in IMAGE_TAGS or identifier in occupied:
                    raise Problem("照片位置无效或位于重复区域内。")
                container = image_container(self.node(identifier))
                if any(paragraph_text(p).strip() for p in container.iter(w("p"))):
                    raise Problem("照片与文字位于同一个组合绘图，请先在 Word 中取消组合。")
            except Problem as exc:
                report(str(exc), [identifier])
        for identifier in plan.remove:
            try:
                node = self.node(identifier)
                if node.tag not in BLOCK_TAGS | IMAGE_TAGS:
                    raise Problem("删除项须为文字区域或图片。")
                ids = self.descendants([image_container(node) if node.tag in IMAGE_TAGS else node])
                overlap = ids & (covered | set(plan.keep))
                covered |= ids
                if overlap:
                    raise Problem("删除项与替换区域重叠。")
            except Problem as exc:
                report(str(exc), [identifier])
        for identifier in plan.keep:
            covered.add(identifier)
            try:
                if self.node(identifier).tag not in {w("p")} | IMAGE_TAGS:
                    raise Problem("请逐段确认固定文字，不能将整个表格直接标为保留。")
            except Problem as exc:
                report(str(exc), [identifier])
        unresolved = [
            row
            for row in inventory["nodes"]
            if row["id"] not in covered and row["kind"] in {"p", "image"} and row["text"].strip()
        ]
        return {
            "errors": list(dict.fromkeys(errors)),
            "issues": issues,
            "unresolved": unresolved,
            "ready": not errors and not unresolved,
        }

    def write(self, output: Path):
        """重写已修改的 XML 部件，其他样式、页设置和资源保持原样。"""
        files = dict(self.files)
        for name, root in self.parts.items():
            files[name] = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
        with ZipFile(output, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)


def relationship_part(part: str) -> str:
    """取得当前 Word 部件的关系文件位置，不接受用户路径。"""
    parent, name = posixpath.split(part)
    return f"{parent}/_rels/{name}.rels"


def relationship_target(part: str, target: str) -> str:
    """按 OPC 包内 URI 解析图片位置，支持绝对部件名和带空格的编码文件名。"""
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), unquote(target))).lstrip("/")
