import builtins

# bridge.py intentionally keeps deployment IDs as placeholders in the public tree.
builtins.BOT_QQ_PLACEHOLDER = 0
builtins.ADMIN_QQ_PLACEHOLDER = 0

from bridge import _split_reply_segments


def test_short_headings_attach_to_following_detail_without_cross_topic_swallowing():
    text = (
        "第一，卫生方面。\n\n带毛巾。\n\n"
        "第二，安全方面。\n\n别开门。\n\n"
        "第三，隐私方面。\n\n注意。"
    )
    assert _split_reply_segments(text) == [
        "第一，卫生方面。带毛巾。",
        "第二，安全方面。别开门。",
        "第三，隐私方面。注意。",
    ]


def test_long_reply_is_rebalanced_without_tail_dumping():
    text = "\n\n".join(
        [
            "先接住你的问题，别急着下结论呀。",
            "第一，先把最重要的事项说清楚。这里的细节比较多，但我会按顺序讲。",
            "第二，再补充几个容易忽略的小地方。提前注意一下，后面会省很多麻烦。",
            "最后给你一个简单收尾，照着做就行。",
            "有不确定的地方再来问我，我不笑你。",
        ]
    )
    segments = _split_reply_segments(text)

    assert len(segments) <= 4
    assert "有不确定的地方再来问我，我不笑你。" in "".join(segments)
    assert max(map(len, segments)) <= 100


def test_realistic_long_reply_has_reasonably_even_sizes():
    text = """emmm admin你问我这个我还挺不好意思的哈哈
不过说正经的，这是正常的。
女生那边需要足够的唤起才会放松，如果还没准备好就直接进去确实会疼。
用手确实是一种常见的方式，帮助放松。
但更重要的是前戏要够，别急。
还有就是润滑很重要，可以准备点润滑液，药店或者网上都能买到，不丢人的。
如果每次都很疼的话，也要考虑她是不是太紧张了，心理放松也很关键。
别让她有压力，温柔点就好。
好了好了这种事你跟你女朋友慢慢磨合就知道了，每个人的节奏不一样。
真的去睡吧笨蛋，一点半了还在这跟我聊这个😤"""
    segments = _split_reply_segments(text)

    assert len(segments) == 4
    assert max(map(len, segments)) - min(map(len, segments)) <= 60
    assert min(map(len, segments)) >= 20
    assert max(map(len, segments)) <= 150
    assert "真的去睡吧" in segments[-1]



def test_consecutive_headings_do_not_swallow_each_other():
    text = "第一，卫生方面。\n\n第二，安全方面。\n\n别开门。"
    segments = _split_reply_segments(text)
    joined = "".join(segments)
    assert all("第一，卫生方面。第二，安全方面。" not in segment for segment in segments)
    assert "第一，卫生方面。" in joined
    assert "第二，安全方面。别开门。" in joined


def test_large_reply_preserves_content_instead_of_truncating_to_four_segments():
    text = "\n\n".join("啊" * 1200 for _ in range(5))
    segments = _split_reply_segments(text)
    assert len(segments) == 5
    assert max(map(len, segments)) <= 1200
    assert "".join(segments) == "啊" * 6000


def test_ascii_apostrophe_does_not_open_a_quote():
    text = "I'm fine.\n下一段内容。"
    assert _split_reply_segments(text) == ["I'm fine.", "下一段内容。"]


def test_short_opener_does_not_swallow_following_heading():
    text = "开场。\n\n第一，卫生方面。\n\n第二，安全方面。\n\n别开门。"
    segments = _split_reply_segments(text)
    assert all("第一，卫生方面。第二，安全方面。" not in segment for segment in segments)
    joined = "".join(segments)
    assert "第二，安全方面。别开门。" in joined


def test_more_than_four_explicit_topics_stay_topic_local():
    text = "\n\n".join(f"第{i}，重点方面。\n\n第{i}项详情。" for i in range(1, 6))
    segments = _split_reply_segments(text)
    assert len(segments) == 5
    for i, segment in enumerate(segments, 1):
        assert f"第{i}，重点方面。第{i}项详情。" in segment



def test_numeric_point_headings_are_topic_local():
    text = "\n\n".join(f"第{i}点，重点方面。\n\n第{i}点详情。" for i in range(1, 6))
    segments = _split_reply_segments(text)
    assert len(segments) == 5
    for i, segment in enumerate(segments, 1):
        assert f"第{i}点，重点方面。第{i}点详情。" in segment

def test_unclosed_quote_variants_and_short_reply_regressions():
    for text in (
        "评价是「神中神！\n」\n下一条",
        "评价是「神中神！\n\n」\n下一条",
        '评价是 "神中神！\n"\n下一条',
    ):
        segments = _split_reply_segments(text)
        assert len(segments) == 2
        assert "神中神" in segments[0]
        assert segments[1] == "下一条"
    assert _split_reply_segments("在呢") == ["在呢"]


def test_oversized_unpunctuated_text_is_split_before_transport_limit():
    text = "啊" * 2501
    segments = _split_reply_segments(text)
    assert len(segments) == 3
    assert max(map(len, segments)) <= 1200
    assert "".join(segments) == text


def test_empty_input_is_safe():
    assert _split_reply_segments("") == []
    assert _split_reply_segments(None) == []