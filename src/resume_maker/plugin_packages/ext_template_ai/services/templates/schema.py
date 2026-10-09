"""把模板已有节点编译为输出候选，模型不能把原文误写成节点标识"""

from typing import Literal

from pydantic import Field, create_model

from resume_maker.domain.templates import RepeatBinding, TemplatePlan, TextBinding


def plan_schema(package, document):
    """限制可选节点和栏目并将引文及结构检查交给映射校验器"""
    nodes = package.inventory()["nodes"]
    paragraphs = tuple(node["id"] for node in nodes if node["kind"] == "p")
    blocks = tuple(node["id"] for node in nodes if node["kind"] in {"p", "tbl", "tr"})
    images = tuple(node["id"] for node in nodes if node["kind"] == "image")
    keep = (*paragraphs, *images)
    if not paragraphs:
        return TemplatePlan
    binding = create_model(
        "CandidateTextBinding", __base__=TextBinding, node=(Literal[paragraphs], ...)
    )
    repeat = create_model(
        "CandidateRepeatBinding",
        __base__=RepeatBinding,
        section=(
            Literal[tuple(dict.fromkeys(["projects", *[s.title for s in document.sections]]))],
            ...,
        ),
        **{key: (Literal[blocks], ...) for key in ("start", "end", "sample_start", "sample_end")},
        fields=(list[binding], Field(min_length=1, max_length=100)),
    )
    return create_model(
        "CandidateTemplatePlan",
        __base__=TemplatePlan,
        fields=(list[binding], Field(max_length=150)),
        repeats=(list[repeat], Field(max_length=40)),
        photos=(
            list[Literal[images]] if images else list[str],
            Field(max_length=10 if images else 0),
        ),
        keep=(list[Literal[keep]], Field(max_length=2000)),
        remove=(list[Literal[(*blocks, *images)]], Field(max_length=2000)),
    )
