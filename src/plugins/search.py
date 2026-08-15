"""搜索命令 /搜索、/search、/搜。"""

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from src.llm.tools_impl import web_search

search_cmd = on_command("搜索", aliases={"search", "搜"}, priority=10)


@search_cmd.handle()
async def handle_search(bot: Bot, event: GroupMessageEvent):
    text = str(event.get_message()).strip()
    for prefix in ["搜索", "search", "搜"]:
        text = text.replace(prefix, "", 1).strip()
    if not text:
        await search_cmd.send(
            MessageSegment.reply(event.message_id) + "请告诉我搜索什么，例如：/搜索 今天的热点新闻"
        )
        return
    await search_cmd.send(MessageSegment.reply(event.message_id) + "🔍 搜索中...")
    result = await web_search(text)
    await search_cmd.send(MessageSegment.reply(event.message_id) + result)
