import builtins

# bridge.py intentionally keeps deployment IDs as placeholders in the public tree.
builtins.BOT_QQ_PLACEHOLDER = 0
builtins.ADMIN_QQ_PLACEHOLDER = 0

from bridge import _split_reply_segments


def test_short_headings_attach_to_following_detail():
    text = "第一，卫生方面。\n\n自带毛巾和拖鞋。\n\n第二，安全方面。\n\n检查房间隐私。"
    segments = _split_reply_segments(text)

    joined = "".join(segments)
    assert "第一，卫生方面。自带毛巾和拖鞋。" in joined
    assert "第二，安全方面。检查房间隐私。" in joined
    assert all(segment not in segments for segment in ("第一，卫生方面。", "第二，安全方面。"))


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


def test_unclosed_quote_and_short_reply_regressions():
    assert _split_reply_segments("评价是「神中神！\n」\n下一条") == ["评价是「神中神！」", "下一条"]
    assert _split_reply_segments("在呢") == ["在呢"]
