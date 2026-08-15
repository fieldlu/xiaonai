"""随机抽签插件 — 自定义人数/排除规则，命令+自然语言双触发."""

import random
import re
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

DEFAULT_EXCLUDE = ["辅导员", "班主任", "班长"]

lucky_cmd = on_command("抽签", aliases={"抽奖", "随机抽", "lucky"}, priority=5)


def _parse_args(text: str) -> tuple[int, list[str]]:
    """Parse count and custom exclude keywords from command text."""
    count = 1
    exclude = list(DEFAULT_EXCLUDE)
    # Remove command prefix
    for prefix in ["抽签", "抽奖", "随机抽", "lucky"]:
        text = text.replace(prefix, "", 1).strip()

    # Check for custom exclude: 排除xxx,xxx
    exc_match = re.search(r"排除\s*[:：]?\s*([^,，\s]+(?:[,，\s]+[^,，\s]+)*)", text)
    if exc_match:
        exclude = [x.strip() for x in re.split(r"[,，\s]+", exc_match.group(1)) if x.strip()]
        text = text.replace(exc_match.group(0), "").strip()

    # Extract number
    num_match = re.search(r"(\d+)", text)
    if num_match:
        count = int(num_match.group(1))
        count = max(1, min(count, 20))  # clamp 1-20

    return count, exclude


BOT_QQ = BOT_QQ_PLACEHOLDER

async def do_lucky_draw(bot: Bot, group_id: int, user_id: int,
                        count: int = 1, exclude: list[str] | None = None) -> str:
    """Execute a lucky draw. Can be called from ai_handler for natural language."""
    if exclude is None:
        exclude = list(DEFAULT_EXCLUDE)

    print(f"[lucky] do_lucky_draw gid={group_id} uid={user_id} count={count} excl={exclude}")
    try:
        members = await bot.get_group_member_list(group_id=group_id)
        print(f"[lucky] got {len(members)} members")
    except Exception as e:
        print(f"[lucky] get_group_member_list failed: {e}")
        return f"获取群成员列表失败：{e}"

    eligible = []
    for m in members:
        if m["user_id"] == BOT_QQ:
            continue  # 不抽小奈自己
        card = (m.get("card") or m.get("nickname") or "").strip()
        if not card:
            continue
        if any(kw in card for kw in exclude):
            continue
        eligible.append(m)
    print(f"[lucky] eligible={len(eligible)}")

    if len(eligible) < count:
        return f"符合条件的人只有 {len(eligible)} 个，不够抽 {count} 人呀~ 试试减少人数或放宽排除条件？"

    winners = random.sample(eligible, count)

    requester_card = ""
    for m in members:
        if m["user_id"] == user_id:
            requester_card = m.get("card") or m.get("nickname") or ""
            break

    lines = [
        f"🎯 抽签结果",
        f"发起人：{requester_card or str(user_id)}",
        f"参与人数：{len(eligible)} 人  |  抽出 {count} 人",
        "",
    ]
    for i, w in enumerate(winners):
        wname = w.get("card") or w.get("nickname") or str(w["user_id"])
        lines.append(f"{'🥇🥈🥉'[i] if i < 3 else '🏅'} {MessageSegment.at(w['user_id'])} {wname}")

    return "\n".join(lines)


@lucky_cmd.handle()
async def handle_lucky(bot: Bot, event: GroupMessageEvent):
    text = str(event.get_message()).strip()
    count, exclude = _parse_args(text)
    try:
        msg = await do_lucky_draw(bot, event.group_id, event.user_id, count, exclude)
    except Exception:
        msg = "获取群成员列表失败了…再试一次吧~"
    await lucky_cmd.finish(msg)
