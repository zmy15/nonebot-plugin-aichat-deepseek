def test_strip_headings_bold_and_italic(fmt) -> None:
    text = "# 标题\n正文 **加粗** 和 *斜体*"
    assert fmt.strip_markdown(text) == "标题\n正文 加粗 和 斜体"


def test_strip_code_blocks(fmt) -> None:
    assert fmt.strip_markdown("```python\nprint(1)\n```") == "print(1)"
    assert fmt.strip_markdown("`code`") == "code"
    assert fmt.strip_markdown("```\nline1\nline2\n```") == "line1\nline2"


def test_strip_quotes_and_lists(fmt) -> None:
    text = "> 引用\n- 列表项\n1. 有序"
    assert fmt.strip_markdown(text) == "引用\n列表项\n有序"


def test_strip_links_and_images(fmt) -> None:
    assert (
        fmt.strip_markdown("[链接](https://example.com)")
        == "链接（https://example.com）"
    )
    assert fmt.strip_markdown("![图片](a.png)") == "图片"
    assert fmt.strip_markdown("<https://example.com>") == "https://example.com"


def test_strip_strike_and_underscore_emphasis(fmt) -> None:
    text = "~~删除~~ 和 _斜体_ 与 __加粗__"
    assert fmt.strip_markdown(text) == "删除 和 斜体 与 加粗"


def test_strip_table(fmt) -> None:
    text = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert fmt.strip_markdown(text) == "a  b\n1  2"


def test_plain_text_is_preserved(fmt) -> None:
    assert fmt.strip_markdown("2 * 3 * 4") == "2 * 3 * 4"
    assert (
        fmt.strip_markdown("deepseek_api_key 和 __init__")
        == "deepseek_api_key 和 __init__"
    )
    assert (
        fmt.strip_markdown("https://example.com/a_b_c")
        == "https://example.com/a_b_c"
    )


def test_escaped_markdown_markers_are_kept(fmt) -> None:
    assert fmt.strip_markdown(r"\*不是斜体\*") == "*不是斜体*"


def test_strip_html_and_entities(fmt) -> None:
    assert fmt.strip_markdown("<b>加粗</b><br>换行 &amp; 符号") == "加粗\n换行 & 符号"


def test_empty_markdown_returns_empty(fmt) -> None:
    assert fmt.strip_markdown("   ") == ""
    assert fmt.strip_markdown("---\n***") == ""


def test_split_text(fmt) -> None:
    assert fmt.split_text("  ", 10) == []
    assert fmt.split_text("short", 100) == ["short"]
    assert fmt.split_text("abcdefghijklmnop", 5) == [
        "abcde",
        "fghij",
        "klmno",
        "p",
    ]
    assert fmt.split_text("line1\nline2\nline3", 12) == ["line1\nline2", "line3"]


def test_split_reply_by_delimiter(fmt) -> None:
    assert fmt.split_reply(
        "第一句|||第二句", delimiter="|||", max_segments=4
    ) == ["第一句", "第二句"]


def test_split_reply_cleans_markdown(fmt) -> None:
    text = "**你好**|||# 标题|||`代码`"
    assert fmt.split_reply(text, delimiter="|||") == ["你好", "标题", "代码"]


def test_split_reply_merges_extra_segments(fmt) -> None:
    text = "a|||b|||c|||d|||e"
    assert fmt.split_reply(text, delimiter="|||", max_segments=3) == [
        "a",
        "b",
        "c d e",
    ]


def test_split_reply_splits_long_segment(fmt) -> None:
    messages = fmt.split_reply("x" * 25, delimiter="|||", max_length=10)
    assert len(messages) == 3
    assert all(len(message) <= 10 for message in messages)
    assert "".join(messages) == "x" * 25


def test_split_reply_without_delimiter_or_content(fmt) -> None:
    assert fmt.split_reply("完整一句话", delimiter="|||") == ["完整一句话"]
    assert fmt.split_reply("|||", delimiter="|||") == []
    assert fmt.split_reply("** **", delimiter="|||") == []
