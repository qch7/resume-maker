"""结构化回复的包装处理回归"""

import json

import pytest

from resume_maker.integrations.providers.codex import structured_text


@pytest.mark.parametrize(
    "message",
    [
        "{}\n```json\n{}\n```",
        "```json\n{}\n```\n[]",
        "```json\n{}\n```\n```json\n{}\n```",
        '说明：{"x": 1}',
        "```json\n{}",
    ],
)
def test_structured_message_cannot_hide_extra_text_or_multiple_results(message):
    """去包装不能吞掉块外结构化数据、多个结果或截断内容"""
    with pytest.raises(ValueError):
        json.loads(structured_text(message))


@pytest.mark.parametrize(
    "prefix,suffix", [("说明如下：\n", ""), ("", "\n映射完成。"), ("已检查 `n1`。\n", "\n结束。")]
)
def test_unique_json_fence_allows_prose_wrapper(prefix, suffix):
    """唯一完整代码块可以忽略非数据说明，字段和节点仍须通过同一严格模型校验"""
    assert json.loads(structured_text(prefix + '```json\n{"x":1}\n```' + suffix)) == {"x": 1}
