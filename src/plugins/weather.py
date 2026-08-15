"""天气查询快捷命令 /天气、/weather。"""

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from config import bot_config
from src.llm.tools_impl import get_weather

weather_cmd = on_command("天气", aliases={"weather"}, priority=10)


@weather_cmd.handle()
async def handle_weather(bot: Bot, event: GroupMessageEvent):
    args = str(event.get_message()).strip()
    city = args.replace("天气", "").replace("weather", "").strip()
    if not city:
        city = bot_config.default_city
    await weather_cmd.send(MessageSegment.reply(event.message_id) + "🔍 查询天气中...")
    result = await get_weather(city)
    if result.startswith("__direct__:"):
        result = result[len("__direct__:"):]
    await weather_cmd.send(MessageSegment.reply(event.message_id) + result)
