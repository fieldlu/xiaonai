import sys
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None
sys.stderr.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stderr, "reconfigure") else None

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    datefmt="%m-%d %H:%M:%S",
    encoding="utf-8",
    errors="replace",
    force=True,
)

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# 显式加载插件
nonebot.load_plugin("src.plugins.ai_handler")
nonebot.load_plugin("src.plugins.weather")
nonebot.load_plugin("src.plugins.news")
nonebot.load_plugin("src.plugins.search")
nonebot.load_plugin("src.plugins.scheduler")
nonebot.load_plugin("src.plugins.earthquake")
nonebot.load_plugin("src.plugins.weather_warning")
nonebot.load_plugin("src.plugins.lucky_draw")
nonebot.load_plugin("src.plugins.personality")

nonebot.run()

