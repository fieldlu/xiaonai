"""工具函数实现：天气、新闻、搜索。"""

import re
import asyncio

import httpx

from config import bot_config

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 天气描述翻译缓存（避免重复调用 LLM）
_WEATHER_TRANSLATION_CACHE: dict[str, str] = {}
_WIND_DIR_CACHE: dict[str, str] = {
    "N": "北风", "NNE": "东北偏北风", "NE": "东北风", "ENE": "东北偏东风",
    "E": "东风", "ESE": "东南偏东风", "SE": "东南风", "SSE": "东南偏南风",
    "S": "南风", "SSW": "西南偏南风", "SW": "西南风", "WSW": "西南偏西风",
    "W": "西风", "WNW": "西北偏西风", "NW": "西北风", "NNW": "西北偏北风",
}
_TRANSLATION_LOCK = None  # lazy init asyncio.Lock

def _get_translation_lock():
    global _TRANSLATION_LOCK
    if _TRANSLATION_LOCK is None:
        import asyncio
        _TRANSLATION_LOCK = asyncio.Lock()
    return _TRANSLATION_LOCK

async def _llm_translate_batch(texts: list[str]) -> dict[str, str]:
    """Batch translate weather descriptions via direct API call."""
    from urllib.parse import quote

    if not texts:
        return {}

    unique = list({t: t for t in texts})  # dedup
    lines = "\n".join(f"{i+1}. {t}" for i, t in enumerate(unique))
    prompt = f"将以下英文天气描述翻译成简短中文（1-5个字），只输出编号+译文，不要解释：\n\n{lines}"

    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            resp = await cli.post(
                f"{bot_config.mimo_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {bot_config.mimo_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mimo-v2.5",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0,
                },
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
    except Exception:
        return {}

    result: dict[str, str] = {}
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or "." not in line:
            continue
        try:
            num_str, trans = line.split(".", 1)
            idx = int(num_str.strip()) - 1
            if 0 <= idx < len(unique):
                result[unique[idx].lower()] = trans.strip()
        except ValueError:
            continue
    return result

async def _translate_weather_batch(descs: list[str]) -> list[str]:
    """Translate a batch of weather descriptions, using cache + LLM for misses."""
    result: list[str] = []
    uncached: list[str] = []

    for d in descs:
        key = d.lower().strip()
        if key in _WEATHER_TRANSLATION_CACHE:
            result.append(_WEATHER_TRANSLATION_CACHE[key])
        else:
            uncached.append(d)
            result.append("")  # placeholder

    if uncached:
        lock = _get_translation_lock()
        async with lock:
            # Double-check after acquiring lock
            still_uncached = []
            for d in uncached:
                key = d.lower().strip()
                if key not in _WEATHER_TRANSLATION_CACHE:
                    still_uncached.append(d)
            if still_uncached:
                translations = await _llm_translate_batch(still_uncached)
                _WEATHER_TRANSLATION_CACHE.update(translations)

        # Fill in placeholders
        idx = 0
        for i in range(len(result)):
            if result[i] == "":
                key = uncached[idx].lower().strip()
                result[i] = _WEATHER_TRANSLATION_CACHE.get(key, uncached[idx])
                idx += 1

    return result

async def _translate_wind_batch(dirs: list[str]) -> list[str]:
    """Translate wind directions, using cache + LLM for misses."""
    result: list[str] = []
    uncached: list[str] = []

    for d in dirs:
        key = d.upper().strip()
        if key in _WIND_DIR_CACHE:
            result.append(_WIND_DIR_CACHE[key])
        else:
            uncached.append(d)
            result.append("")

    if uncached:
        lock = _get_translation_lock()
        async with lock:
            still_uncached = []
            for d in uncached:
                key = d.upper().strip()
                if key not in _WIND_DIR_CACHE:
                    still_uncached.append(d)
            if still_uncached:
                lines = "\n".join(f"{i+1}. {d}" for i, d in enumerate(still_uncached))
                prompt = f"将以下英文风向缩写翻译成中文风向（如 N→北风, WNW→西北偏西风）：\n\n{lines}"
                try:
                    async with httpx.AsyncClient(timeout=10) as cli:
                        resp = await cli.post(
                            f"{bot_config.mimo_base_url}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {bot_config.mimo_api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": "mimo-v2.5",
                                "messages": [{"role": "user", "content": prompt}],
                                "max_tokens": 100,
                                "temperature": 0,
                            },
                        )
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                except Exception:
                    content = ""
                for line in content.strip().split("\n"):
                    line = line.strip()
                    if not line or "." not in line:
                        continue
                    try:
                        num_str, trans = line.split(".", 1)
                        idx = int(num_str.strip()) - 1
                        if 0 <= idx < len(still_uncached):
                            _WIND_DIR_CACHE[still_uncached[idx].upper()] = trans.strip()
                    except ValueError:
                        continue

        for i in range(len(result)):
            if result[i] == "":
                key = uncached[0].upper().strip()
                result[i] = _WIND_DIR_CACHE.get(key, uncached[0])
                uncached.pop(0)

    return result

def _translate_weather(desc: str) -> str:
    """Translate English weather description to Chinese, handling compound descriptions."""
    if not desc:
        return desc
    import re
    parts = re.split(r",\s*|\s+and\s+", desc, flags=re.IGNORECASE)
    return "，".join(p.strip() for p in parts if p.strip())

async def _do_translate_weather(desc: str) -> str:
    """Async translate weather desc with LLM."""
    if not desc:
        return desc
    import re
    parts = [p.strip() for p in re.split(r",\s*|\s+and\s+", desc, flags=re.IGNORECASE) if p.strip()]
    if not parts:
        return desc
    translated = await _translate_weather_batch(parts)
    return "，".join(translated)

async def _get_smart_advice(city: str, temp: str, feels: str, humidity: str,
                            weather_desc: str, wind_dir: str, wind_speed: str,
                            lo: str, hi: str, uv_index: str = "", chance_of_rain: str = "") -> str:
    """Generate intelligent clothing and umbrella advice via DeepSeek."""
    from datetime import datetime
    month = datetime.now().month
    season = "春季" if 3 <= month <= 5 else "夏季" if 6 <= month <= 8 else "秋季" if 9 <= month <= 11 else "冬季"

    # Pre-process context hints
    try:
        t_lo = int(lo); t_hi = int(hi); t_swing = t_hi - t_lo
    except Exception:
        t_swing = 0

    swing_note = ""
    if t_swing >= 12:
        swing_note = f"昼夜温差高达{t_swing}°C，一定要提醒分层叠穿，方便随时脱。"
    elif t_swing >= 8:
        swing_note = f"昼夜温差{t_swing}°C，早晚需要加件外套。"

    uv_note = ""
    if uv_index:
        try:
            uv = int(uv_index)
            if uv >= 7:
                uv_note = f"紫外线强度{uv}（很强），提醒涂防晒。"
            elif uv >= 4:
                uv_note = f"紫外线强度{uv}（中等），适当防晒即可。"
        except ValueError:
            pass

    rain_note = ""
    if chance_of_rain and chance_of_rain != "0":
        try:
            rain_pct = int(chance_of_rain)
            if rain_pct >= 60:
                rain_note = f"降雨概率{rain_pct}%，强烈建议带伞。"
            elif rain_pct >= 30:
                rain_note = f"降雨概率{rain_pct}%，最好备把伞。"
        except ValueError:
            pass

    prompt = f"""你是小奈，温柔可爱的QQ机器人。根据下面的天气信息，给同学一段穿衣建议和带伞提醒。像朋友聊天一样自然可爱。

城市：{city}（{season}）
天气：{weather_desc}
温度：{lo}~{hi}°C（当前{temp}°C，体感{feels}°C）
湿度：{humidity}%
风向风速：{wind_dir} {wind_speed}km/h
{uv_note}{rain_note}{swing_note}

穿衣参考规则：
- 高温>28°C：短袖/裙子，注意防晒防暑
- 高温20~28°C：短袖+薄长裤，早晚可能需要薄外套
- 高温15~20°C：长袖或薄卫衣刚好
- 高温8~15°C：毛衣/加绒卫衣+外套
- 高温<8°C：厚外套/羽绒服，注意保暖
- 湿度>80%且高温>25°C：闷热，建议穿透气轻薄的衣服
- 风力>20km/h：风大，建议穿防风外套
- 体感比实际低3°C以上时按更冷一档推荐
- 昼夜温差≥8°C一定要提醒叠穿，方便中午脱
- 天气预报中有雨一定要提醒带伞

用1-2句话给出建议，30-60字。直接输出建议，不要任何前缀。"""

    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            resp = await cli.post(
                f"{bot_config.mimo_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {bot_config.mimo_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mimo-v2.5",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 120,
                    "temperature": 0.7,
                },
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        # Enhanced fallback: multi-factor rule-based advice
        parts = []
        desc_lower = weather_desc.lower()
        rain_kw = ["rain", "drizzle", "shower", "雨", "阵雨", "雷", "雪", "snow", "毛毛雨", "暴雨", "冰雹"]
        if any(k in desc_lower for k in rain_kw) or (chance_of_rain and chance_of_rain != "0"):
            parts.append("🌂 记得带伞哦~")

        try:
            t_lo = int(lo); t_hi = int(hi); t_feels = int(feels)
            swing = t_hi - t_lo
            hum = int(humidity)

            effective = t_feels if abs(t_feels - int(temp)) >= 3 else ((t_lo + t_hi) // 2)

            if effective >= 30:
                if hum > 70:
                    parts.append("🥵 闷热！短袖短裤最凉快，多喝水~")
                else:
                    parts.append("☀️ 短袖短裤，注意防晒~")
            elif effective >= 25:
                if hum > 80:
                    parts.append("👕 短袖就行，闷热注意透气~")
                else:
                    parts.append("👕 短袖刚好，凉快~")
            elif effective >= 20:
                if swing >= 10:
                    parts.append("🧥 短袖+薄外套叠穿，温差大方便调整~")
                else:
                    parts.append("👔 长袖薄衫刚好~")
            elif effective >= 15:
                if swing >= 8:
                    parts.append("🧥 卫衣+外套叠穿，早晚凉中午暖~")
                else:
                    parts.append("👔 薄外套或卫衣~")
            elif effective >= 8:
                parts.append("🧥 毛衣或加绒卫衣+外套~")
            else:
                parts.append("🧣 穿厚点！羽绒服安排上~")

            if int(wind_speed) >= 25:
                parts.append("💨 风大，穿件抗风的~")

            if uv_index:
                try:
                    if int(uv_index) >= 7:
                        parts.append("🧴 紫外线强，涂防晒！")
                except ValueError:
                    pass
        except (ValueError, TypeError):
            pass

        return " ".join(parts) if parts else ""

async def get_weather(city: str, day_offset: int = -1) -> str:
    """查询天气。QWeather（7天+生活指数）优先，回退 wttr.in。"""
    from config import bot_config

    _CITY_IDS = {
        "北京": "101010100", "长春": "101060101", "长沙": "101250101", "成都": "101270101",
        "大连": "101070201", "福州": "101230101", "广州": "101280101", "贵阳": "101260101",
        "哈尔滨": "101050101", "海口": "101310101", "杭州": "101210101", "合肥": "101220101",
        "香港": "101320101", "昆明": "101290101", "拉萨": "101140101", "兰州": "101160101",
        "澳门": "101330101", "南昌": "101240101", "南京": "101190101", "南宁": "101300101",
        "青岛": "101120201", "厦门": "101230201", "上海": "101020100", "深圳": "101280601",
        "沈阳": "101070101", "苏州": "101190401", "台北": "101340101", "天津": "101030100",
        "乌鲁木齐": "101130101", "武汉": "101200101", "西安": "101110101", "西宁": "101150101",
        "银川": "101170101", "郑州": "101180101", "重庆": "101040100",
    }

    qw_id = _CITY_IDS.get(city)
    if qw_id and bot_config.qw_api_key:
        base = bot_config.qw_api_host or "https://devapi.qweather.com"
        async with httpx.AsyncClient(timeout=8) as client:
            try:
                resp_now, resp_7d, resp_idx = await asyncio.gather(
                    client.get(f"{base}/v7/weather/now?location={qw_id}&key={bot_config.qw_api_key}"),
                    client.get(f"{base}/v7/weather/7d?location={qw_id}&key={bot_config.qw_api_key}"),
                    client.get(f"{base}/v7/indices/1d?location={qw_id}&key={bot_config.qw_api_key}&type=1,2,3,5,8,9"),
                )
                data_now = resp_now.json()
                data_7d = resp_7d.json()
                data_idx = resp_idx.json()
                if data_now.get("code") == "200":
                    now = data_now.get("now", {})
                    daily = data_7d.get("daily", []) if data_7d.get("code") == "200" else []
                    indices = data_idx.get("daily", []) if data_idx.get("code") == "200" else []

                    temp = now.get('temp', '?')
                    feels = now.get('feelsLike', '?')
                    weather_desc = now.get('text', '')
                    wind_dir = now.get('windDir', '')
                    wind_scale = now.get('windScale', '')
                    humidity = now.get('humidity', '?')

                    day_labels = ["今天", "明天", "后天", "大后天", "3天后", "4天后", "5天后"]

                    if day_offset >= 0 and daily and day_offset < len(daily):
                        d = daily[day_offset]
                        wd = d.get("textDay", "")
                        lo = d.get("tempMin", "?")
                        hi = d.get("tempMax", "?")
                        label = day_labels[day_offset] if day_offset < 7 else d["fxDate"]
                        result = f"\U0001f324 {city} {label}天气：{wd}，温度 {lo}\u00b0C ~ {hi}\u00b0C，当前 {temp}\u00b0C，湿度 {humidity}%，{wind_dir} {wind_scale}级"

                        # Query indices for today
                        if day_offset == 0 and indices:
                            result += await _format_indices(indices)
                        return result

                    # Full overview (day_offset == -1)
                    result = f"\U0001f324 {city} 当前天气：{weather_desc}，温度 {temp}\u00b0C，体感 {feels}\u00b0C，湿度 {humidity}%，{wind_dir} {wind_scale}级"

                    if daily:
                        result += "\n\U0001f4c5 未来一周："
                        for i, d in enumerate(daily[:7]):
                            label = day_labels[i] if i < 7 else d["fxDate"]
                            lo = d.get("tempMin", "?")
                            hi = d.get("tempMax", "?")
                            wd = d.get("textDay", "")
                            result += f"\n  \u00b7 {label}：{wd}，{lo}~{hi}\u00b0C"

                    if indices:
                        idx_icons = {"1": "\U0001f3c3", "2": "\U0001f697", "3": "\U0001f455", "5": "\U0001f506", "8": "\U0001f60a", "9": "\U0001f31e"}
                        result += "\n\U0001f3af 生活指数："
                        for idx in indices[:6]:
                            name = idx.get("name", "")
                            level = idx.get("level", "")
                            category = idx.get("category", "")
                            icon = idx_icons.get(idx.get("type", ""), "\u2022")
                            result += f"\n  {icon} {name}：{category}（{level}级）"

                    return result
            except Exception:
                pass  # Fall through to wttr.in

    # Fallback: wttr.in
    import urllib.parse
    encoded_city = urllib.parse.quote(city.encode("utf-8"))
    url = f"https://wttr.in/{encoded_city}?format=j1"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
            data = resp.json()
        except Exception:
            return f"查询 {city} 天气失败，请稍后再试。"
    try:
        cur = data["current_condition"][0]
    except (KeyError, IndexError):
        return f"未找到城市：{city}"
    import re as _re
    def _split_compound(desc: str) -> list[str]:
        return [p.strip() for p in _re.split(r",\s*|\s+and\s+", desc, flags=_re.IGNORECASE) if p.strip()]
    raw_descs: list[str] = []
    raw_descs.extend(_split_compound(cur["weatherDesc"][0]["value"]))
    wind_dir_raw = cur["winddir16Point"]
    weather_data = data.get("weather", [])
    for d in weather_data[:3]:
        try:
            raw_descs.extend(_split_compound(d["hourly"][4]["weatherDesc"][0]["value"]))
        except (KeyError, IndexError):
            pass
    cn_list = await _translate_weather_batch(raw_descs)
    cn_map: dict[str, str] = {}
    for r, t in zip(raw_descs, cn_list):
        cn_map[r.lower().strip()] = t
    current_parts = _split_compound(cur["weatherDesc"][0]["value"])
    weather_desc = "，".join(cn_map.get(p.lower().strip(), p) for p in current_parts)
    wind_cn_list = await _translate_wind_batch([wind_dir_raw])
    wind_dir = wind_cn_list[0] if wind_cn_list else wind_dir_raw
    temp = cur["temp_C"]
    feels = cur["FeelsLikeC"]
    humidity = cur["humidity"]
    wind_speed = cur["windspeedKmph"]
    day_labels = ["今天", "明天", "后天"]
    if day_offset >= 0 and weather_data and day_offset < len(weather_data):
        d = weather_data[day_offset]
        date = d["date"]
        fparts = _split_compound(d["hourly"][4]["weatherDesc"][0]["value"])
        wd = "，".join(cn_map.get(p.lower().strip(), p) for p in fparts)
        lo = d["mintempC"]
        hi = d["maxtempC"]
        label = day_labels[day_offset] if day_offset < 3 else date
        result = f"\U0001f324 {city} {label}天气：{wd}，温度 {lo}\u00b0C ~ {hi}\u00b0C，当前 {temp}\u00b0C，湿度 {humidity}%，{wind_dir} {wind_speed}km/h"
        uv = cur.get("uvIndex", "")
        rain = d["hourly"][4].get("chanceofrain", "") if d.get("hourly") and len(d.get("hourly", [])) > 4 else ""
        advice = await _get_smart_advice(city, int(temp), int(feels), int(humidity), wd, wind_dir, wind_speed, int(lo), int(hi), uv, rain)
        if advice:
            result += f"\n\n{advice}"
    else:
        result = f"\U0001f324 {city} 当前天气：{weather_desc}，温度 {temp}\u00b0C，体感 {feels}\u00b0C，湿度 {humidity}%，{wind_dir} {wind_speed}km/h\n"
        if weather_data:
            result += "\U0001f4c5 未来三天：\n"
            for i, d in enumerate(weather_data[:3]):
                label = day_labels[i] if i < 3 else d["date"]
                lo = d["mintempC"]
                hi = d["maxtempC"]
                fparts = _split_compound(d["hourly"][4]["weatherDesc"][0]["value"])
                wd = "，".join(cn_map.get(p.lower().strip(), p) for p in fparts)
                result += f"  \u00b7 {label}：{wd}，{lo}~{hi}\u00b0C\n"
        if weather_data:
            d0 = weather_data[0]
            rain = d0["hourly"][4].get("chanceofrain", "") if d0.get("hourly") and len(d0.get("hourly", [])) > 4 else ""
            advice = await _get_smart_advice(city, int(temp), int(feels), int(humidity), weather_desc, wind_dir, wind_speed, int(d0["mintempC"]), int(d0["maxtempC"]), cur.get("uvIndex", ""), rain)
            if advice:
                result += f"\n\U0001f4a1 {advice}"
    return result

async def _format_indices(indices: list) -> str:
    """Format lifestyle indices as text."""
    icons = {"1": "\U0001f3c3", "2": "\U0001f697", "3": "\U0001f455", "5": "\U0001f506", "8": "\U0001f60a", "9": "\U0001f31e"}
    result = ""
    for idx in indices[:6]:
        name = idx.get("name", "")
        category = idx.get("category", "")
        level = idx.get("level", "")
        icon = icons.get(idx.get("type", ""), "\u2022")
        result += f"\n  {icon} {name}：{category}"
    return result

async def get_news(category: str = "") -> str:
    """Fetch news via shared scheduler.fetch_raw_news for unified cache & config."""
    from src.plugins.scheduler import fetch_raw_news
    import os, json as _json
    data_dir = os.environ.get("QQBOT_DATA_DIR", "data")
    config_path = os.path.join(data_dir, "news_config.json")
    count = 10
    if os.path.exists(config_path):
        try: count = _json.load(open(config_path, encoding="utf-8")).get("count", 10)
        except: pass
    raw = await fetch_raw_news(count)
    if not raw: return "No news today."
    articles_text = ""
    for i, item in enumerate(raw, 1):
        if "||DESC||" in item:
            title, desc = item.split("||DESC||", 1)
            articles_text += f"Article {i}: {title}\nContent: {desc}\n\n"
        else:
            articles_text += f"Article {i}: {item}\n\n"
    return articles_text if articles_text else "No news today."
async def scrape_page(url: str = "", selector: str = "", extract_mode: str = "text") -> str:
    """Use Scrapling to scrape a page with CSS selector. extract_mode: text/markdown/html/links."""
    if not url:
        return "Please provide a URL."
    if not url.startswith("http"):
        url = "https://" + url
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=12, follow_redirects=True)

        if page.status != 200:
            return f"Failed to fetch page: HTTP {page.status}"

        if extract_mode == "links":
            links = page.css("a::attr(href)").getall()
            texts = page.css("a::text").getall()
            result = []
            for i, (href, txt) in enumerate(zip(links, texts)):
                txt = txt.strip()
                if txt and href and href.startswith("http"):
                    result.append(f"{i+1}. [{txt}]({href})")
            return "\n".join(result[:30]) if result else "No links found."

        if selector:
            elements = page.css(selector)
            if not elements:
                return f"No elements found matching '{selector}'."
            if extract_mode == "html":
                return "\n---\n".join(el.html for el in elements[:10])
            elif extract_mode == "markdown":
                # Scrapling has built-in markdown conversion
                try:
                    return page.markdown
                except Exception:
                    pass
            # Default: text
            return "\n---\n".join(el.text.strip() for el in elements[:20] if el.text.strip())

        # No selector: return page summary
        title = page.css_first("title")
        title_text = title.text.strip() if title else "No title"
        body_text = page.get_text(separator="\n")
        lines = [l.strip() for l in body_text.splitlines() if l.strip()]
        summary = "\n".join(lines[:80])
        if len(summary) > 3000:
            summary = summary[:3000] + "...(truncated)"
        return f"Title: {title_text}\n\n{summary}"

    except ImportError:
        return "Scrapling not available. Falling back to basic fetch."
    except Exception as e:
        return f"Scrape failed: {e}"

async def fetch_url(url: str = "") -> str:
    """Fetch and read a URL/webpage. Returns title + content summary."""
    if not url:
        return "Please provide a URL."
    if not url.startswith("http"):
        url = "https://" + url
    try:
        from src.search.parser import fetch_page
        page = await fetch_page(url, timeout=12.0)
        if page.error:
            return f"Failed to read this page: {page.error}\n\nTry searching for the content instead."
        title = page.title or "No title"
        content = page.extract or page.full_text[:1500]
        if len(content) > 1500:
            content = content[:1500] + "...(truncated)"
        return f"Page title: {title}\n\nContent summary:\n{content}"
    except Exception as e:
        return f"Failed to fetch URL: {e}"

async def web_search(query: str = "", num: int = 5) -> str:
    """Search + auto-read top result for direct answer."""
    if not query:
        return "Please provide search keywords."
    full_query = query
    words = query.strip().split()
    if len(words) > 2:
        query = " ".join(words[:2])
    try:
        from src.search.engine import search_and_read
        data = await search_and_read(query, n=10, read_pages=0)
        results = data.get("results", [])
        pages = data.get("pages", [])
        if not results:
            return "No results found for: " + query
        lines = [full_query + " found " + str(len(results)) + " results:"]
        for i, r in enumerate(results[:5], 1):
            lines.append(str(i) + ". " + r["title"] + " - " + r["engine"])
        if pages and pages[0].extract:
            p = pages[0]
            clean = re.sub(r"\s+", " ", p.extract[:3000]).strip()
            if clean:
                lines.append("")
                lines.append("[Top page: " + (p.title or "") + "]")
                lines.append(clean)
                lines.append("[Answer based on the page content above in Chinese, 2-3 sentences, natural tone.]")
        lines.append("")
        lines.append("[IMPORTANT: Answer the user's question based on the search results above. Do NOT call more search tools or fetch more URLs - the results above are sufficient. Answer in Chinese, 2-3 paragraphs, natural tone.]")
        return chr(10).join(lines)
    except Exception as e:
        return "Search failed: " + str(e)

async def deep_search(question: str = "", num: int = 8) -> str:
    """Multi-keyword deep search for complex questions. Breaks question into
    multiple search queries, searches in parallel, deduplicates and ranks results.
    Use for complex/nuanced questions where a single keyword search wont suffice."""
    if not question or len(question) < 2:
        return "Please provide a question to search."
    try:
        from src.search.deep_search import deep_search as _deep_search
        data = await _deep_search(question, n=min(num, 10), read_pages=1)
        results = data.get("results", [])
        pages = data.get("pages", [])
        queries_used = data.get("queries_used", [])
        if not results:
            return "No results found: " + question + ". Try different wording."
        lines = ["Deep search: " + question + " found " + str(len(results)) + " results (searched: " + ", ".join(queries_used[:4]) + "):"]
        for i, r in enumerate(results[:min(num, 10)], 1):
            lines.append(str(i) + ". " + r["title"] + " - " + r["url"] + " (" + r["engine"] + ")")
        if pages:
            lines.append("")
            lines.append("Key page summaries:")
            for p in pages[:3]:
                lines.append("--- " + (p.title or "No title") + " ---")
                lines.append(p.extract[:2000])
        lines.append("")
        lines.append("[IMPORTANT: Answer the user's question based on the search results above. Do NOT call more search tools or fetch more URLs - the results above are sufficient. Answer in Chinese, 2-3 paragraphs, natural tone.]")
        return chr(10).join(lines)
    except Exception as e:
        return "Deep search failed: " + str(e)

async def ocr_image(image_url: str = "", lang: str = "chi_sim+eng") -> str:
    """Understand content of an image. Use when a user sends an image/picture/photo/screenshot. Uses MiMo multimodal vision (not just OCR) to understand both text and visual content."""
    if not image_url:
        return "Please provide an image URL."
    try:
        import base64, os as _os

        if image_url.startswith("file://"):
            tmp_path = image_url[7:]
            with open(tmp_path, "rb") as f:
                img_data = f.read()
            suffix = _os.path.splitext(tmp_path)[1]
            content_type_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
            content_type = content_type_map.get(suffix.lower(), "image/png")
        else:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cli:
                resp = await cli.get(image_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                if resp.status_code != 200:
                    return f"Failed to download image: HTTP {resp.status_code}"
                img_data = resp.content
                content_type = resp.headers.get("content-type", "image/jpeg")

        img_b64 = base64.b64encode(img_data).decode()

        user_content = [
            {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{img_b64}"}},
            {"type": "text", "text": "请详细描述这张图片的内容。如果图中有文字，请完整识别。如果是照片/截图/图表，请描述你看到的所有细节。请用中文回答。"}
        ]

        async with httpx.AsyncClient(timeout=60) as cli:
            resp = await cli.post(
                f"{bot_config.mimo_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {bot_config.mimo_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mimo-v2.5",
                    "messages": [{"role": "user", "content": user_content}],
                    "max_tokens": 2000,
                },
            )
            data = resp.json()
            description = data["choices"][0]["message"]["content"]
            if not description:
                return "The image could not be understood. It may be too blurry or in an unsupported format."

        result = f"[AI视觉识别结果]\n{description.strip()}\n\n[提示: 以上是AI对图片内容的完整理解，包括文字和视觉信息。请基于此回答用户问题。]"
        return result[:4000]

    except Exception as e:
        # Fallback: try Tesseract OCR
        try:
            import tempfile, subprocess, os as __os
            from PIL import Image
            if image_url.startswith("file://"):
                tmp_path = image_url[7:]
                suffix = __os.path.splitext(tmp_path)[1] or ".png"
            else:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cli:
                    resp = await cli.get(image_url)
                    if resp.status_code != 200:
                        return f"OCR fallback failed: HTTP {resp.status_code}"
                    suffix = ".jpg"
                    ct = resp.headers.get("content-type", "")
                    if "png" in ct: suffix = ".png"
                    elif "gif" in ct: suffix = ".gif"
                    elif "webp" in ct: suffix = ".webp"
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                        f.write(resp.content)
                        tmp_path = f.name
            if suffix != ".png":
                img = Image.open(tmp_path)
                png_path = tmp_path + ".png"
                img.save(png_path, "PNG")
                __os.unlink(tmp_path)
                tmp_path = png_path
            out_path = tmp_path + "_out"
            result = subprocess.run(
                ["tesseract", tmp_path, out_path, "-l", lang, "--oem", "1"],
                capture_output=True, text=True, timeout=30
            )
            text = ""
            if result.returncode == 0 and __os.path.exists(out_path + ".txt"):
                with open(out_path + ".txt", "r", encoding="utf-8") as f:
                    text = f.read().strip()
            for p in [tmp_path, out_path + ".txt"]:
                try: __os.unlink(p)
                except: pass
            if text:
                return f"OCR fallback result (MiMo vision unavailable):\n{text[:3000]}"
        except:
            pass
        return f"Image understanding error: {e}"
async def _fetch_whut_html(url: str, client) -> str:
    """Fetch WHUT page and return cleaned HTML."""
    try:
        return await client.get_page_html(url)
    except Exception:
        return ""

def _extract_items(html: str) -> list[tuple[str, str, str]]:
    """从 HTML 中提取 (日期, 标题, 链接)。"""
    # 先从纯文中提取带日期的条目
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    text_items = re.findall(r'【([^】]*)】\s*(.*?)\s*(\d{4}-\d{2}-\d{2})', text)

    # 从 HTML 中提取所有链接
    link_map = {}  # title → url
    for m in re.finditer(r'<a[^>]*href="(https://webvpn[^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL):
        url, title_html = m.group(1), m.group(2)
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        if title and len(title) >= 4:
            link_map[title] = url
            # 也存短标题（取前15字）
            link_map[title[:15]] = url

    # 匹配条目和链接
    result = []
    for dept, title, date in text_items:
        title = title.strip()
        if len(title) <= 5:
            continue
        # 尝试匹配链接
        url = link_map.get(title) or link_map.get(title[:15]) or ""
        result.append((date, title, url, dept.strip()))

    return [(d, t, u) for d, t, u, _ in result]

# 多个搜索源页面
WHUT_SEARCH_PAGES = [
    ("工作通知", "https://webvpn.whut.edu.cn/http/77726476706e69737468656265737421f9b95694322426557a1dc7af96/xxtg/gztz_9764.shtml"),
    ("学院通告", "https://webvpn.whut.edu.cn/http/77726476706e69737468656265737421f9b95694322426557a1dc7af96/xytg/"),
    ("会议安排", "https://webvpn.whut.edu.cn/http/77726476706e69737468656265737421f9b95694322426557a1dc7af96/xxtg/xxhy_9765.shtml"),
]

async def _fetch_all_pages(urls: list[str], client) -> list[str]:
    """并发抓取多个页面。"""
    tasks = [_fetch_whut_html(u, client) for u in urls]
    return await asyncio.gather(*tasks)

async def whut_get_page(url: str = "", keyword: str = "") -> str:
    """访问YOUR_SCHOOL webvpn 页面，自动翻页+多源搜索，返回标题+链接。"""
    from src.whut.client import whut_client

    # 决定抓取哪些页面
    if url:
        page_urls = [url]
    elif keyword:
        # 从多个源搜索
        page_urls = [u for _, u in WHUT_SEARCH_PAGES]
    else:
        page_urls = [WHUT_SEARCH_PAGES[0][1]]

    all_htmls = await _fetch_all_pages(page_urls, whut_client)
    all_htmls = [h for h in all_htmls if h]
    if not all_htmls:
        return "访问 webvpn 失败"

    # 各页面自动翻页
    all_html = list(all_htmls)
    for html in list(all_htmls):
        pm = re.search(r'createPageHTML\(\s*(\d+)\s*,\s*(\d+)\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', html)
        if pm:
            total, current, _, ext = int(pm.group(1)), int(pm.group(2)), pm.group(3), pm.group(4)
            base_url = re.sub(rf'(?:(_\d+)?\.{ext})$', '', page_urls[all_htmls.index(html)])
            if not base_url.startswith("http"):
                continue
            tasks = [_fetch_whut_html(f"{base_url}_{p}.{ext}", whut_client)
                     for p in range(current + 1, min(total, current + 4))]
            extras = await asyncio.gather(*tasks)
            all_html.extend(h for h in extras if h)

    # 提取所有条目
    seen = set()
    all_items = []
    for h in all_html:
        for date, title, link in _extract_items(h):
            key = f"{date}_{title}"
            if key not in seen:
                seen.add(key)
                all_items.append((date, title, link))

    # 按日期降序
    all_items.sort(key=lambda x: x[0], reverse=True)

    # 关键词模糊搜索（标题）
    if keyword:
        kw = keyword.lower()
        all_items = [x for x in all_items if kw in x[1].lower()]

    if all_items:
        result = []
        for date, title, link in all_items[:30]:
            result.append(f"[{date}] {title}\n   {link}")
        label = "通知公告" if not keyword else f"搜索「{keyword}」结果"
        return f"{label}（共{len(all_items)}条）：\n\n" + "\n\n".join(result)

    if keyword:
        return f"未找到包含「{keyword}」的通知。"

    return "暂未获取到数据。"

# ---- 校内通知搜索 (via WebVPN) ----

WEBVPN_CAMPUS_NOTICE = "https://webvpn.whut.edu.cn/http/77726476706e69737468656265737421f9b95694322426557a1dc7af96/xxtg/gztz_9764.shtml"

async def search_campus_notice(keyword: str = "") -> str:
    """Search campus notices via WebVPN."""
    import re
    from src.whut.client import whut_client

    try:
        html = await whut_client.get_page_html(WEBVPN_CAMPUS_NOTICE)
    except Exception as e:
        print(f"[campus] WebVPN fetch failed: {e}")
        return "校园通知暂时无法获取（WebVPN 连接失败，请稍后重试）。"

    notices = []
    seen = set()

    # WebVPN rewrites all href to absolute webvpn URLs
    for m in re.finditer(
        r'<a[^>]*href="(https://webvpn\.whut\.edu\.cn[^"]*)"[^>]*title="([^"]*)"[^>]*>',
        html, re.DOTALL
    ):
        url = m.group(1)
        title = m.group(2).strip()
        if url not in seen and len(title) > 10:
            seen.add(url)
            dept_match = re.match(r"【([^】]*)】\s*(.*)", title)
            if dept_match:
                dept = dept_match.group(1)
                text = dept_match.group(2)
            else:
                dept = ""
                text = title
            notices.append({"dept": dept, "title": text, "url": url})

    print(f"[campus] WebVPN fetched {len(notices)} notices")

    # Also try auto.whut.edu.cn via WebVPN (use whut_get_page)
    try:
        auto_html = await whut_client.get_page_html(
            "https://webvpn.whut.edu.cn/http/77726476706e69737468656265737421f9b95694322426557a1dc7af96/xxtg/gztz_9764.shtml"
        )
        # Try a second URL format for auto
        # For now, skip auto if we have enough notices
    except Exception:
        pass

    if not notices:
        return "暂未获取到校内通知数据（校内系统可能正在维护）。"

    # Keyword filter
    if keyword:
        kw = keyword.lower()
        notices = [n for n in notices if kw in n["title"].lower() or kw in n["dept"].lower()]

    if not notices:
        return f"未找到包含「{keyword}」的通知。"

    result_parts = []
    for n in notices[:15]:
        prefix = f"【{n['dept']}】" if n["dept"] else ""
        result_parts.append(f"{prefix}{n['title']}\n{n['url']}")

    label = f"搜索「{keyword}」结果" if keyword else "最新校内通知"
    output = f"📋 {label}（共{len(notices)}条）：\n\n" + "\n\n".join(result_parts)
    output += "\n\n[重要] 你回复时必须每条保留标题+链接，不要省略任何链接。"
    return output

# ---- 管理员工具 ----

async def admin_check_user(qq: int) -> str:
    return f"__admin__:check:{qq}"

async def admin_set_affection(qq: int, score: int, dimension: str = "affection") -> str:
    return f"__admin__:set_aff:{qq}:{score}:{dimension}"

async def admin_inject_knowledge(topic: str, content: str) -> str:
    return f"__admin__:inject_kb:{topic}|||{content}"

async def list_knowledge() -> str:
    return "__admin__:list_kb"

async def delete_knowledge(topic: str) -> str:
    return f"__admin__:delete_kb:{topic}"

async def admin_add_memory(qq: int, fact: str) -> str:
    return f"__admin__:add_mem:{qq}:{fact}"

async def admin_news_control(action: str, value: str = "", target_type: str = "") -> str:
    return f"__admin__:news:{action}:{value}:{target_type}"

async def admin_weather_control(action: str, value: str = "", target_type: str = "") -> str:
    return f"__admin__:weather:{action}:{value}:{target_type}"

async def weather_control(action: str) -> str:
    return f"__admin__:weather_ctrl:{action}"

async def disaster_control(action: str) -> str:
    return f"__admin__:disaster:{action}"

async def earthquake_control(action: str) -> str:
    return f"__admin__:earthquake:{action}"

async def admin_send_message(target: int = 0, message: str = "", is_group: bool = True) -> str:
    g = "1" if is_group else "0"
    return f"__admin__:send:{target}:{g}:{message}"

async def set_alarm(time_str: str, message: str, is_group: bool = False, target_group: int = 0) -> str:
    encoded = message.replace("|", "/")
    group_flag = "1" if is_group else "0"
    return f"__alarm__:set:{time_str}|{encoded}|{group_flag}|{target_group}"

async def list_alarms() -> str:
    return "__alarm__:list"

async def cancel_alarm(alarm_id: str) -> str:
    return f"__alarm__:cancel:{alarm_id}"

# ---- 抽签工具 ----

async def group_lucky_draw(count: int = 1, exclude: str = "") -> str:
    return f"__lucky__:draw:{count}:{exclude}"

# ---- 传话筒 ----

async def relay_message(qq: int, message: str, anonymous: bool) -> str:
    anon = "1" if anonymous else "0"
    return f"__relay__:{qq}:{anon}:{message}"

# ---- 通知同学 ----

async def notify_classmate(name: str, message: str) -> str:
    """Look up a classmate by name in the contact list and prepare notification."""
    import os
    kb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge")
    kb_path = os.path.join(kb_dir, "YOUR_CONTACTS_FILE.md")
    if not os.path.exists(kb_path):
        return "__notify__:error:通讯录文件不存在，请先导入YOUR_STUDENT_LIST"
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.strip().split("\n")
        matched_name = None
        matched_qq = None
        for line in lines:
            line = line.strip()
            if not line.startswith("|") or "---" in line:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2:
                if cells[1] == name:
                    matched_qq = cells[0]
                    matched_name = cells[1]
                    break
                if matched_qq is None and name in cells[1]:
                    matched_qq = cells[0]
                    matched_name = cells[1]
        if matched_qq:
            return f"__notify__:{matched_qq}:{matched_name}:{message}"
        return f"__notify__:error:通讯录里没找到叫「{name}」的同学，试试说全名？"
    except Exception as e:
        return f"__notify__:error:查通讯录出错了：{str(e)[:100]}"

async def notify_all(message: str) -> str:
    """Send a notification to everyone in the contact list."""
    import os
    kb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge")
    kb_path = os.path.join(kb_dir, "YOUR_CONTACTS_FILE.md")
    if not os.path.exists(kb_path):
        return "__notify_all__:error:通讯录文件不存在"
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            content = f.read()
        qqs = []
        names = []
        seen_qqs = set()
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line.startswith("|") or "---" in line:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2 and cells[0].isdigit() and cells[0] not in seen_qqs:
                seen_qqs.add(cells[0])
                qqs.append(cells[0])
                names.append(cells[1])
        if qqs:
            if len(message) > 500:
                return f"__notify_all__:error:消息内容太长（{len(message)}字符），请精简到500字以内"
            joined = ",".join(qqs)
            return f"__notify_all__:{joined}:{message}"
        return "__notify_all__:error:通讯录是空的"
    except Exception as e:
        return f"__notify_all__:error:{str(e)[:100]}"

# ---- 记忆工具 ----

async def remember(fact: str) -> str:
    """让机器人记住关于当前用户的事实。"""
    return "__memory__:remember:" + fact

async def recall() -> str:
    """让机器人回忆当前用户的所有记忆。"""
    return "__memory__:recall"

async def check_affection(qq: int = 0) -> str:
    if qq and qq > 10000:
        return f"__memory__:check_affection:{qq}"
    return "__memory__:check_affection"

async def adjust_affection(delta: int, reason: str, dimension: str = "affection") -> str:
    return f"__memory__:adjust_affection:{delta}:{reason}:{dimension}"

async def admin_group_control(action: str, value: str = "") -> str:
    return f"__admin__:group:{action}:{value}"

async def course_advisor(question: str, semester: int = 0, direction: str = "", completed_courses: str = "") -> str:
    parts = [question, str(semester), direction, completed_courses]
    return "__course__:advise:" + "|||".join(parts)

async def teacher_advisor(question: str, teacher_name: str = "", research_interest: str = "") -> str:
    parts = [question, teacher_name, research_interest]
    return "__teacher__:advise:" + "|||".join(parts)

async def search_knowledge(query: str = "") -> str:
    import os, json
    kb_dir = "data/knowledge"
    idx_path = os.path.join(kb_dir, "index.json")
    if not os.path.exists(idx_path):
        return "no kb index"
    try:
        idx = json.loads(open(idx_path, encoding="utf-8").read())
    except Exception:
        return "kb index read error"
    if not idx:
        return "kb empty"
    q = query.lower().strip()
    scored = []
    for topic in idx:
        fname = topic.replace("/", "_").replace(chr(92), "_") + ".md"
        fpath = os.path.join(kb_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            kc = open(fpath, encoding="utf-8").read()
        except Exception:
            continue
        s = 0
        if q in topic.lower():
            s += 10
        for w in q.replace(" ", "").replace(chr(0xff0c), ",").split(","):
            w = w.strip()
            if not w:
                continue
            if w in kc:
                s += 3
            if w in topic.lower():
                s += 2
        if s > 0:
            scored.append((s, topic, kc))
    if not scored:
        return "no match: " + query
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:3]
    if len(top) == 1:
        _, topic, kc = top[0]
        return "[KB] " + topic + chr(10) + kc.strip()
    lines = ["Found " + str(len(top)) + " entries:"]
    for _, topic, kc in top:
        lines.append(chr(10) + "--- " + topic + " ---")
        lines.append(kc.strip())
    return chr(10).join(lines)

async def news_control(action: str) -> str:
    return "__admin__:news_ctrl:" + action


async def _summarize_news(articles_text: str) -> str:
    '''Shared news summarizer - used by both get_news and transform_news.'''
    from datetime import datetime
    _now = datetime.now()
    _wday = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][_now.weekday()]
    prompt = (
        "你是小奈，一个用QQ聊天的大学女生。你要把今天的新闻分享给同学们。\n"
        f"今天是{_now.month}月{_now.day}日 {_wday}。\n"
        + "\n【格式铁律 — 必须严格遵守】\n"
        + "大家下午好呀~小奈来播报今天的热点新闻啦(｡･ω･｡)\n"
        + "1. [两个emoji] [新闻标题概括]，小奈觉得[1-2句可爱评论]~\n"
        + "2. [两个emoji] [新闻标题概括]，小奈希望[1-2句可爱评论]~\n"
        + "3. [两个emoji] [新闻标题概括]，小奈[动词][1-2句可爱评论]~\n"
        + "...\n"
        + "[结尾：大家xx加油呀/注意xx哦 之类的可爱收尾]\n"
        + "\n规则：\n"
        + "- 每条新闻用两个相关emoji开头\n"
        + "- 标题用自己的话概括，不要照抄原标题\n"
        + "- 每条都要有小奈的可爱评论（觉得/希望/相信/提醒/感觉）\n"
        + "- 语气自然可爱，像真实女大学生聊天，不是AI播报\n"
        + "- 不要用Markdown、不要编号加粗\n"
        + "- 输出纯文字，直接可发QQ\n"
        + "\n今天的热点：\n" + articles_text
        + "\n现在用小奈的语气写新闻播报：" )
    try:
        from config import bot_config
        async with httpx.AsyncClient(timeout=25) as cli:
            r = await cli.post(f"{bot_config.mimo_base_url}/chat/completions",
                json={"model":"mimo-v2.5","messages":[{"role":"user","content":prompt}],"max_tokens":1024},
                headers={"Authorization": f"Bearer {bot_config.mimo_api_key}"})
            result = r.json()["choices"][0]["message"]["content"].strip()
            if result: return result
    except Exception as e:
        print(f"[summarize_news] LLM failed: {e}")
    return articles_text[:200]


async def sing_song(song_query: str) -> str:
    import json, os
    songs_file = os.path.join("data/songs", "songs.json")
    try:
        with open(songs_file, "r", encoding="utf-8") as f:
            songs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        songs = {}
    if not songs:
        return "曲库是空的，我还没学会唱歌。"
    q = song_query.strip().lower()
    best = None
    for name, info in songs.items():
        if q in name.lower() or name.lower() in q:
            best = (name, info)
            break
    if not best:
        song_list = "、".join(songs.keys())
        return f"我还没学会唱《{song_query}》，但我会唱这些：{song_list}。想听哪首？"
    name, info = best
    file_path = os.path.join("data/songs", info["file"])
    if not os.path.exists(file_path):
        return f"歌曲文件《{name}》找不到了。"
    return f"__song__:{os.path.abspath(file_path)}:{name}"

# Voice profiles for edge-tts
VOICE_PROFILES = {
    "xiaoxiao": ("zh-CN-XiaoxiaoNeural", "温柔女声，默认，日常聊天"),
    "yunyang": ("zh-CN-YunyangNeural", "专业男声，新闻/正式通知"),
    "yunxi": ("zh-CN-YunxiNeural", "阳光男声，轻松话题"),
    "xiaoyi": ("zh-CN-XiaoyiNeural", "活泼女声，搞笑/可爱"),
    "yunjian": ("zh-CN-YunjianNeural", "激情男声，体育/比赛"),
    "yunxia": ("zh-CN-YunxiaNeural", "可爱男声，卖萌"),
    "liaoning": ("zh-CN-liaoning-XiaobeiNeural", "东北话女声，幽默"),
    "shaanxi": ("zh-CN-shaanxi-XiaoniNeural", "陕西话女声，方言"),
}

STYLE_SSML = {
    "general": None,
    "cheerful": "cheerful",
    "sad": "sad",
    "angry": "angry",
    "excited": "excited",
    "gentle": "gentle",
    "fearful": "fearful",
    "calm": "calm",
}

async def say_voice(text: str, target_qq: int = 0, voice: str = "xiaoxiao", style: str = "general") -> str:
    '''Generate voice message from text using edge-tts. Supports 8 voices + 7 emotional styles + caching.'''
    import subprocess, tempfile, os, hashlib

    voice_name, _ = VOICE_PROFILES.get(voice, VOICE_PROFILES["xiaoxiao"])

    # Cache: hash(text + voice + style) -> persistent mp3
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "voice_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_key = hashlib.md5(f"{text}|{voice}|{style}".encode("utf-8")).hexdigest()
    cache_path = os.path.join(cache_dir, f"{cache_key}.mp3")

    if os.path.exists(cache_path) and os.path.getsize(cache_path) >= 100:
        return f"__voice__:{target_qq}:{cache_path}:{text[:100]}"

    # Build SSML if style is specified
    final_text = text
    style_name = STYLE_SSML.get(style)
    if style_name:
        final_text = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="zh-CN"><voice name="' + voice_name + '"><mstts:express-as style="' + style_name + '">' + text + '</mstts:express-as></voice></speak>'

    # Trim long text (edge-tts has practical limits)
    if len(final_text) > 3000:
        final_text = final_text[:3000]

    try:
        r = subprocess.run(
            [os.path.expanduser("~/.local/bin/edge-tts"), "--voice", voice_name, "--text", final_text, "--write-media", cache_path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return f"语音生成失败：{r.stderr[:100]}"
        file_size = os.path.getsize(cache_path)
        if file_size < 100:
            return "语音生成失败：音频文件太小"
        return f"__voice__:{target_qq}:{cache_path}:{text[:100]}"
    except Exception as e:
        return f"语音生成失败：{e}"


TOOL_IMPL: dict[str, callable] = {
    "get_weather": get_weather,
    "get_news": get_news,
    "web_search": web_search,
    "check_affection": check_affection,
    "adjust_affection": adjust_affection,
    "remember": remember,
    "recall": recall,
    "admin_check_user": admin_check_user,
    "admin_set_affection": admin_set_affection,
    "admin_inject_knowledge": admin_inject_knowledge,
    "list_knowledge": list_knowledge,
    "search_knowledge": search_knowledge,
    "delete_knowledge": delete_knowledge,
    "admin_add_memory": admin_add_memory,
    "admin_news_control": admin_news_control,
    "admin_weather_control": admin_weather_control,
    "earthquake_control": earthquake_control,
    "weather_control": weather_control,
    "disaster_control": disaster_control,
    "admin_send_message": admin_send_message,
    "set_alarm": set_alarm,
    "list_alarms": list_alarms,
    "cancel_alarm": cancel_alarm,
    "search_campus_notice": search_campus_notice,
    "group_lucky_draw": group_lucky_draw,
    "relay_message": relay_message,
    "scrape_page": scrape_page,
    "fetch_url": fetch_url,
    "deep_search": deep_search,
    "ocr_image": ocr_image,
    "admin_group_control": admin_group_control,
    "course_advisor": course_advisor,
    "sing_song": sing_song,
    "say_voice": say_voice,
    "news_control": news_control,
    "notify_classmate": notify_classmate,
    "notify_all": notify_all,
    "teacher_advisor": teacher_advisor,
}
