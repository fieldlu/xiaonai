"""新闻查询快捷命令 /新闻、/news。"""

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from src.llm.tools_impl import get_news

news_cmd = on_command("新闻", aliases={"news"}, priority=10)


@news_cmd.handle()
async def handle_news(bot: Bot, event: GroupMessageEvent):
    text = str(event.get_message()).strip()
    cat = ""
    if "科技" in text or "tech" in text.lower():
        cat = "tech"
    elif "财经" in text or "金融" in text:
        cat = "finance"
    await news_cmd.send(MessageSegment.reply(event.message_id) + "🔍 获取新闻中...")
    result = await get_news(cat)
    await news_cmd.send(MessageSegment.reply(event.message_id) + result)
