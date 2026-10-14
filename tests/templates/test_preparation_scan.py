"""模板归一化只扫描相关内容，脚注缓存随部件改写及时失效"""

from lxml import etree

from resume_maker.integrations.word.ooxml import NS, w
from resume_maker.integrations.word.templates import fields, prepare


def test_complex_field_scan_skips_unrelated_format_nodes():
    """大量样式节点不进入域状态机，同时保留完整页码的边界信息"""
    root = etree.Element(w("document"))
    for _ in range(2000):
        etree.SubElement(etree.SubElement(root, w("rPr")), w("b"))
    etree.SubElement(root, w("fldChar")).set(w("fldCharType"), "begin")
    etree.SubElement(root, w("instrText")).text = " PAGE "
    etree.SubElement(root, w("fldChar")).set(w("fldCharType"), "separate")
    etree.SubElement(root, w("t")).text = "1"
    etree.SubElement(root, w("fldChar")).set(w("fldCharType"), "end")
    visited = []

    class CountedRoot:
        """记录状态机真正访问的节点数量"""

        def iter(self, *tags):
            """透明转发筛选遍历并记录进入状态机的节点"""
            for node in root.iter(*tags):
                visited.append(node)
                yield node

    actual = fields.complex_fields(CountedRoot())
    assert len(visited) == 5
    assert len(actual) == 1
    assert actual[0].kind == "PAGE"
    assert actual[0].complete and actual[0].has_result and not actual[0].invalid


def test_filtered_field_scan_keeps_nested_and_independent_stories():
    """正文嵌套域不吞并文本框页码，不同脚注中的边界不能拼成完整域"""
    root = etree.Element(w("document"))

    def control(parent, kind):
        """向指定故事添加域边界"""
        etree.SubElement(parent, w("fldChar")).set(w("fldCharType"), kind)

    control(root, "begin")
    etree.SubElement(root, w("instrText")).text = " AUTHOR "
    control(root, "separate")
    textbox = etree.SubElement(root, w("txbxContent"))
    control(textbox, "begin")
    etree.SubElement(textbox, w("instrText")).text = " PAGE "
    control(textbox, "separate")
    etree.SubElement(textbox, w("t")).text = "1"
    control(textbox, "end")
    control(root, "begin")
    etree.SubElement(root, w("instrText")).text = " DATE "
    control(root, "separate")
    etree.SubElement(root, w("t")).text = "显示内容"
    control(root, "end")
    control(root, "end")
    note = etree.SubElement(root, w("footnote"))
    control(note, "begin")
    etree.SubElement(note, w("instrText")).text = " PAGE "
    control(etree.SubElement(root, w("footnote")), "end")
    actual = fields.complex_fields(root)
    assert [(item.kind, item.complete, item.has_result) for item in actual] == [
        ("AUTHOR", True, True),
        ("PAGE", True, True),
        ("DATE", True, True),
        ("PAGE", False, False),
    ]
    assert fields.freeze_fields(root) == ["AUTHOR", "DATE", "PAGE"]
    assert list(root.iter(w("instrText"))) == list(textbox.iter(w("instrText")))
    assert len(list(root.iter(w("fldChar")))) == 3


def reference_part(kind="document"):
    """生成带有效脚注引用的独立文字部件"""
    root = etree.Element(w(kind), nsmap={"w": NS["w"]})
    paragraph = etree.SubElement(root, w("p"))
    etree.SubElement(paragraph, w("footnoteReference")).set(w("id"), "1")
    return etree.tostring(root)


def test_note_ids_are_parsed_once_across_unchanged_parts(monkeypatch):
    """多个正文部件共用脚注身份集合，避免每个部件重新解析相同脚注 XML"""
    notes = etree.Element(w("footnotes"))
    etree.SubElement(notes, w("footnote")).set(w("id"), "1")
    data = etree.tostring(notes)
    files = {f"word/header{index}.xml": reference_part("hdr") for index in range(12)}
    files["word/footnotes.xml"] = data
    reads = []
    original = etree.fromstring

    def counted(value, *args, **kwargs):
        """只统计同一脚注原始字节的解析次数"""
        if value is data:
            reads.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(prepare.etree, "fromstring", counted)
    assert prepare.prepare_parts(files) == []
    assert len(reads) == 2
    assert all(b"footnoteReference" in files[f"word/header{index}.xml"] for index in range(12))


def test_note_id_cache_refreshes_after_accepting_revisions():
    """脚注部件接受修订后重新读取身份集合，后续部件可保留新生效的引用"""
    notes = etree.Element(w("footnotes"))
    inserted = etree.SubElement(notes, w("ins"))
    etree.SubElement(inserted, w("footnote")).set(w("id"), "1")
    files = {
        "word/document.xml": reference_part(),
        "word/footnotes.xml": etree.tostring(notes),
        "word/header1.xml": reference_part("hdr"),
    }
    notices = prepare.prepare_parts(files)
    assert b"footnoteReference" not in files["word/document.xml"]
    assert b"footnoteReference" in files["word/header1.xml"]
    assert any("接受修订" in notice for notice in notices)
    assert any("失效的脚注" in notice for notice in notices)
