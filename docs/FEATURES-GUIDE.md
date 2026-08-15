# 🧰 功能全览与配置手册（超详细版）

> 本手册覆盖 XiaoNai 的**全部功能**：每个功能都有「功能详解 → 配置方法 → 使用命令 → 数据存储」四段。
> 所有命令、配置字段均从源码逐一提取验证，可直接照做。
>
> 新手请先看 [保姆级教程](BEGINNER-GUIDE.md)；本文是功能字典，随用随查。

---

## 目录

- [零、部署前置（必读）](#零部署前置必读)
- [一、聊天核心功能](#一聊天核心功能)
- [二、38 个对话工具完整清单](#二38-个对话工具完整清单)
- [三、查询类工具详解](#三查询类工具详解)
- [四、定时推送详解](#四定时推送详解)
- [五、群管理与订阅](#五群管理与订阅)
- [六、运维管理](#六运维管理)
- [七、可选高级功能](#七可选高级功能)
- [附录 A：占位符完整清单](#附录-a占位符完整清单)
- [附录 B：数据文件一览表](#附录-b数据文件一览表)
- [附录 C：已知问题与陷阱](#附录-c已知问题与陷阱)

---

## 零、部署前置（必读）

### 0.1 占位符替换（不做会报错）

源码使用大量占位符，**不替换会在运行时 NameError 或行为异常**。发布/部署前全局替换：

```bash
grep -rl "ADMIN_QQ_PLACEHOLDER" . | xargs sed -i 's/ADMIN_QQ_PLACEHOLDER/你的QQ号/g'
grep -rl "CLASS_GROUP_PLACEHOLDER" . | xargs sed -i 's/CLASS_GROUP_PLACEHOLDER/班级群号/g'
# 同理替换 BOT_QQ_PLACEHOLDER / CHAT_GROUP_PLACEHOLDER / TEST_GROUP_PLACEHOLDER /
#           CADRE_GROUP_PLACEHOLDER / RESOURCE_GROUP_PLACEHOLDER / YOUR_SCHOOL / YOUR_MAJOR ...
```

完整清单见 [附录 A](#附录-a占位符完整清单)。

> ⚠️ `CLASS_GROUP_PLACEHOLDER` 直接出现在 `scheduler_v5.py` 的默认配置字典里（L45-49），**不替换 scheduler 直接启动失败**。

### 0.2 运行环境

| 项 | 要求 |
|----|------|
| 部署路径 | `/opt/xiaonai`（代码内统一硬编码，勿改目录名；或用 symlink 兼容） |
| Python | 3.10+（venv 建议 `/opt/xiaonai/venv`） |
| 服务 | systemd：`xiaonai-bridge` / `xiaonai-scheduler`（见 `scripts/`） |
| NapCat | OneBot v11 WebSocket 监听 `127.0.0.1:3001`；HTTP API `127.0.0.1:3000` |
| 依赖 | `pip install -r requirements.txt`（+ 可选 `requirements-dev.txt`） |

### 0.3 `.env` 全字段说明（config.py → pydantic BotConfig）

```env
# ========== LLM（必填，任选其一或都填） ==========
MIMO_API_KEY=              # MiMo / OpenCode 的 key（主 LLM，模型固定 mimo-v2.5）
MIMO_BASE_URL=             # 默认 https://opencode.ai/zen/go/v1
DEEPSEEK_API_KEY=          # 备用模型 key
DEEPSEEK_BASE_URL=         # 默认 https://api.deepseek.com/v1

# ========== 和风天气（天气查询/推送/气象预警） ==========
QW_API_KEY=                # 和风天气 key
QW_API_HOST=               # 控制台分配的私有域名（如 xxx.re.qweatherapi.com）；留空回落 https://devapi.qweather.com

# ========== NapCat / OneBot ==========
NONE_BOT_PORT=8080
ONEBOT_WS_URLS=ws://127.0.0.1:3001

# ========== 机器人身份 ==========
BOT_ADMINS=[你的QQ号]      # 管理员（班长）QQ，JSON 数组格式
DEFAULT_CITY=武汉           # 默认城市（/天气 无参时）

# ========== 推送目标群（也可用 subscribe 命令管理） ==========
NEWS_GROUPS=[]
WEATHER_GROUPS=[]

# ========== 校园系统（可选） ==========
WHUT_USERNAME=             # 学号（WebVPN/CAS 登录）
WHUT_PASSWORD=             # 密码
WHUT_VPN_TICKET=           # 可选：直接注入 wengine_vpn_ticket 免登录
WEBVPN_PROXY=http://127.0.0.1:40000
```

> 补充：代码还引用 `XIAONAI_ADMIN_QQ`（health_notify.py，默认 ADMIN_QQ_PLACEHOLDER）。`config.py` 设置了 `extra="allow"`，多余变量不会报错。

---

## 一、聊天核心功能

### 1. AI 智能对话 💬

**功能详解**
- 灵魂功能。统一 LLM 客户端（`src/llm/client.py`）：OpenAI 兼容 `AsyncOpenAI`，模型**固定 `mimo-v2.5`**，自动拼接 ①系统人格（SYSTEM_PROMPT，内置铁律：纯文字无 Markdown、禁表格、短聊 2-3 句、称呼一律用"ta"、跨群隐私隔离等）②小奈情绪上下文 ③知识库上下文（启动时加载 `data/knowledge/index.json` + 各 `.md`）。
- 支持 function calling（38 个工具，见第二章）；`max_tokens` 默认 8192；请求超时 25s。
- 返回 `{content, reasoning_content(思维链), tool_calls}`，输出自动清洗 Markdown 符号。

**配置方法**
```env
MIMO_API_KEY=你的key
MIMO_BASE_URL=https://opencode.ai/zen/go/v1   # 可换任意 OpenAI 兼容端点
```
- 换模型需改代码：`src/llm/client.py` 中 `model="mimo-v2.5"`。
- 知识库上下文：把 `.md` 放入 `data/knowledge/` 后跑 `python3 search/rebuild_kb_index.py`。

**使用**：私聊/群里直接发消息。群内是否回复取决于群类型（见第五章）。

**数据存储**：读 `data/knowledge/index.json` + `*.md`。

---

### 2. 图片识图 / OCR 🖼

**功能详解**
- 工具 `ocr_image`（tools_impl L647-742）：**MiMo 视觉优先**（图片 base64 内联，max_tokens 2000，超时 60s）→ 失败回退本地 **Tesseract**（`-l chi_sim+eng --oem 1`，超时 30s）。
- 插件 `ocr_helper.py`：从消息中提取 `[CQ:image,...url=...]`（最多 3 张），下载（15s 超时）→ GIF 取首帧 / WebP 转 PNG / RGBA 白底合成 → OCR，结果 `\n---\n` 拼接，返回前 1500 字符。

**配置方法**
- 需要 `MIMO_API_KEY`（视觉通道）。
- 本地回退需要系统装 Tesseract 中文包：
  ```bash
  sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim   # Debian/Ubuntu
  # Windows: 下载 UB Mannheim 版安装并勾选 Chinese (Simplified)
  ```

**使用**：QQ 里直接发图片，自动识别并回复。

**数据存储**：临时 PNG/TXT，用后即删。

---

### 3. 记忆系统 💾

**功能详解**
- **三层会话记忆**（`src/memory/store.py` v3）：好感度 + 事实记忆（去重保留 50 条，>25 条自动摘要，只留最新 15 条）+ 智能上下文（昵称/摘要/相关记忆≤8 条/好感档位/关系阶段/聊天统计注入 LLM）+ 情绪追踪（moods 保留 30 条）。
- **被动观察器**（`passive_observer.py`）：本地约 25 条正则免费提取事实（通知/考试/身份/名字/位置/喜好/计划等，每条 ≤30 字最多 3 条）+ 高信息量消息进缓冲池（上限 40 条）**批量交 LLM（DeepSeek）提取**（60 分钟最多一次）；敏感内容（色情/自残/毒品/赌博）红线不提取；噪声过滤 L0-L7 级。
- **四层记忆架构**（`src/memory/layers.py`）：L0 瞬态（内存 20 条）→ L1 短期（SQLite+FTS，带 importance）→ L2 长期 → L3 全局知识库（confidence 0-1 可调）；`search_all` 合并检索；L1 超 7 天可升迁 L2。
- **用户大五人格**（`personality_engine.py`）：15 条正则推断 OCEAN 五维（±3/命中），>20 条消息后每 10 条向 50 回归 90%，生成人格上下文注入 LLM。

**配置方法**
- 可选环境变量 `QQBOT_DATA_DIR`（默认 `data`，注意：`xiaonai_memory.py` 默认取脚本目录/data，`store.py` 默认取相对工作目录/data，两者基准不同）。
- 无其他配置，全部自动运行。

**使用**（CLI，`xiaonai_memory.py`）
```bash
python3 xiaonai_memory.py recall <QQ号> [关键词]          # 回忆记忆（关键词打分 top10）
python3 xiaonai_memory.py remember <QQ号> <事实>           # 手动添加记忆
python3 xiaonai_memory.py affection <QQ号>                 # 查看好感度
python3 xiaonai_memory.py radar <QQ号>                     # 好感度字符雷达图
python3 xiaonai_memory.py stage <QQ号>                     # 当前关系阶段
python3 xiaonai_memory.py set_affection <QQ号> <分数> [维度]  # 设置维度分数
python3 xiaonai_memory.py check_user <QQ号>                # 用户全部数据
python3 xiaonai_memory.py list_users                       # 用户列表
python3 xiaonai_memory.py process <QQ号> <文本> [--group]  # 手动跑一条消息的处理管线
```

**数据存储**：`data/memory/users/<uid>.json`（用户记忆）、SQLite（L1/L2/L3 表）、`data/diary/`（日记汇总）。

---

### 4. 好感度引擎 ❤️

**功能详解**
- **8 维好感度模型**（`affection_dimensions.py` + `affection_engine.py`；早期版本是 6 维，旧数据自动补 50）：

| 维度 | label | 权重 | 典型档位（分数区间 → 文案） |
|------|-------|------|------|
| affection | 好感度 | 0.30 | 0-5 完全陌生 / 25-35 还不错的朋友 / 55-62 越来越在意 / 78-85 非常非常重要 / 98-101 已经完全沦陷了 |
| closeness | 亲近度 | 0.17 | 0-20 客气疏离 / 40-55 日常陪伴 / 70-85 无话不聊 / 85-101 形影不离 |
| trust | 信任度 | 0.17 | 0-20 有所保留 / 40-60 愿意分享 / 75-90 知无不言 |
| tacit | 默契度 | 0.08 | 0-25 频道对接中 / 50-65 心有灵犀有时有 / 80-101 灵魂共频 |
| dependency | 依赖度 | 0.08 | 0-20 独立自主 / 40-60 习惯找小奈 / 75-90 离不开小奈了 |
| understanding | 了解度 | 0.08 | 0-20 还不了解 / 40-60 比较了解 / 75-90 比 ta 自己还懂 ta |
| protectiveness | 守护欲 | 0.08 | 0-20 无所谓 / 40-60 放心不下 / 75-90 谁都不能欺负 ta |
| sharing | 分享欲 | 0.04 | 0-20 惜字如金 / 40-60 乐于分享 / 75-90 什么都跟你讲 |

- **增长机制**：情感分析（LLM 优先、3s 超时回落关键词）→ 8 维 delta 计算（正面/负面词、长消息、提问、分享、颜文字、波浪线等信号 ×SENSITIVITY=1.5）→ 上限减速（>95 正向 ×0.1、>85 ×0.5）→ 0-100 钳制。普通正面消息约 +1~3 分。
- **衰减**：>168h 不聊天 closeness/trust/dependency/protectiveness 衰减；>72h、>24h 两档更轻衰减。
- **群聊隔离**：群里只更新 closeness/tacit/sharing 三维（私聊才全维度）。
- **里程碑系统**：首次突破 60/75/90 🔓、综合分日跳升 ≥5 ⚡、连续聊天 3/7/30 天 🔥、记忆条数 10/25/50 🧠。
- **关系阶段**（composite_score 加权求和）：点头之交 → 还不错的朋友 → 放在心上的朋友 → 每天不聊两句就少了点什么 → 越来越在意 → 很特别的存在 → 藏在心底的人 → 心里最柔软的角落 → 已经完全沦陷了。
- 每周日 22:00 好感度周报（scheduler 插件，只打印不推送）。

**配置方法**：无。全部自动。数据在 `data/memory/users/<uid>.json`。

**使用**（对话中自动）：查好感 → 工具 `check_affection`；调好感 → `adjust_affection`（管理员）；CLI 见上一节。

---

### 5. 小奈情绪 🌤

**功能详解**（`src/memory/mood.py`）
- 小奈自身情绪每 4 小时刷新：6 种状态（元气满满/普通日常/有点困/想撒娇/心情低落/想同学了），按时段随机（6-9 元气、13-16 犯困、18-21 元气/撒娇、22-5 困/低落）+ 互动修正（互动多能量 +1、低落转日常、班长说话能量 +2、15% 随机突变）。
- 情绪以 tone_map 注入 LLM 语气（如低落时回复变短）。

**配置方法**：无。数据 `data/mood_state.json`、`data/interaction_today.json`。
> ⚠️ 占位符注意：`mood.py` L154 使用 `ADMIN_QQ_PLACEHOLDER`，需替换。

---

### 6. 群内抽签 🎲

**功能详解**（`src/plugins/lucky_draw.py`）
- 命令+自然语言双触发：`on_command("抽签", aliases={"抽奖","随机抽","lucky"})`。
- 支持人数（钳制 1-20）与排除规则：`排除xxx,xxx`；默认排除辅导员/班主任/班长。
- 从群成员列表随机抽取，剔除机器人自己与无名片成员，🥇🥈🥉/🏅 + @。

**配置方法**：替换 `BOT_QQ_PLACEHOLDER`（lucky_draw.py L36）。

**使用**（群内）：
```
抽签
抽签 3
抽奖 2 排除学习委员
```

---

### 7. 语音回复 🔊

**功能详解**（工具 `say_voice`，tools_impl L1218-1255）
- edge-tts 朗读：**8 种音色**（xiaoxiao 晓晓/ yunyang 云扬/ yunxi 云希/ xiaoyi 晓伊/ yunjian 云健/ yunxia 云夏/ liaoning 晓颜/ shaanxi 晓萱）+ **7 种情绪风格**（SSML express-as）；文本超 3000 字截断。
- 生成结果 MD5 缓存到 `data/voice_cache/*.mp3`（同文本不重复生成）。

**配置方法**（服务器）
```bash
pip install edge-tts
# 确保可执行文件在 ~/.local/bin/edge-tts 或 PATH 中（代码用 os.path.expanduser 解析）
```

**使用**：对话说「用语音说...」触发。

**数据存储**：`data/voice_cache/{md5}.mp3`。

---

### 8. 唱歌 🎤

**功能详解**（工具 `sing_song`，tools_impl L1170-1193）
- 从曲库 `data/songs/songs.json` 匹配歌曲名，返回音频文件路径播放。

**配置方法**：创建曲库
```json
// data/songs/songs.json
{ "歌名": { "file": "相对路径/音频文件.mp3" } }
```

**使用**：对话说「唱一首XXX」触发。

---

### 9. 定时闹钟提醒 ⏰

**功能详解**
- 对话工具：`set_alarm`（HH:MM 或 YYYY-MM-DD HH:MM）/ `list_alarms` / `cancel_alarm`（前缀匹配防截断），返回 `__alarm__:` 协议由 bridge 消费。
- CLI（`alarm_manager.py`）：时间解析支持 `HH:MM`（今天该点，已过 +1 天）/ `YYYY-MM-DD HH:MM` / `Nmin`（相对 N 分钟后），全部北京时间 UTC+8。
- NoneBot 插件侧（`src/plugins/scheduler.py` L287-364）：APScheduler date job，持久化 `alarms.json`，**启动自动恢复未过期闹钟**；到期发 `⏰ 闹钟响了~` 并自动清理。
- 触发方式：scheduler 插件（对话设置）或 `alarm_manager.py check`（由 proactive_check.py 每 10 分钟调用，经 bridge HTTP :8081/send 派发）。

**配置方法**：无。数据 `data/alarms.json`。
> ⚠️ CLI 默认闹钟归属 `ADMIN_QQ_PLACEHOLDER` 私聊，需替换占位符。

**使用**
```bash
python3 admin/alarm_manager.py set "08:00" "该起床啦"
python3 admin/alarm_manager.py set "2026-06-01 08:00" "考试日"
python3 admin/alarm_manager.py set "30min" "30分钟后提醒"
python3 admin/alarm_manager.py list
python3 admin/alarm_manager.py cancel <id尾部>
python3 admin/alarm_manager.py check      # 输出到期闹钟（由 proactive_check 调用）
```

---

## 二、38 个对话工具完整清单

> 工具定义在 `src/llm/tools.py`（注入 LLM 做 function calling），实现在 `src/llm/tools_impl.py`（`TOOL_IMPL` 注册表）。分两类：**真实实现型**（直接返回内容）与**占位符协议型**（返回 `__前缀__:` 特殊字符串，由 bridge/ai_handler 消费执行）。

| # | 工具名 | 用途 / 触发场景 | 类型 |
|---|--------|----------------|------|
| 1 | `admin_check_user` | 【管理员】查看用户全部数据（记忆/好感度） | 协议 |
| 2 | `admin_set_affection` | 【管理员】设置某用户维度分数（0-100） | 协议 |
| 3 | `admin_add_memory` | 【管理员】手动添加记忆 | 协议 |
| 4 | `admin_news_control` | 【管理员】新闻/校园早报推送控制（13 种 action） | 协议 |
| 5 | `get_weather` | 查任意城市天气（今天/明天/后天），QWeather 优先 wttr.in 回退，含穿衣/带伞建议 | **真实** |
| 6 | `admin_weather_control` | 【管理员】天气推送控制 | 协议 |
| 7 | `admin_send_message` | 发消息到指定 QQ 群 | 协议 |
| 8 | `set_alarm` | 设置闹钟（HH:MM / YYYY-MM-DD HH:MM） | 协议 |
| 9 | `list_alarms` | 查看闹钟 | 协议 |
| 10 | `cancel_alarm` | 取消闹钟 | 协议 |
| 11 | `search_campus_notice` | 搜校内通知（WebVPN 工作通知页，部门【】前缀过滤） | **真实** |
| 12 | `relay_message` | 传话筒：代用户传话给指定 QQ | 协议 |
| 13 | `remember` | 记住当前用户告知的事实 | 协议 |
| 14 | `recall` | 回忆当前用户全部记忆 | 协议 |
| 15 | `check_affection` | 查看好感度/关系数据 | 协议 |
| 16 | `adjust_affection` | 调整某维度分数（delta -5~+5） | 协议 |
| 17 | `group_lucky_draw` | 群内抽签（count≤20，exclude 排除词） | 协议 |
| 18 | `search_knowledge` | 知识库搜索（主题命中+10/内容含词+3，top3） | **真实** |
| 19 | `web_search` | 网页搜索 + 自动读 Top 结果（engine.search_and_read） | **真实** |
| 20 | `get_news` | 今日新闻含摘要（条数读 news_config.json count，默认 10） | **真实** |
| 21 | `fetch_url` | 抓取并总结 URL 内容（截 1500 字） | **真实** |
| 22 | `deep_search` | 复杂问题深搜（查询分解 + 多源并行 + 读页） | **真实** |
| 23 | `admin_inject_knowledge` | 【管理员】注入知识点到知识库 | 协议 |
| 24 | `list_knowledge` | 列出知识库所有主题 | 协议 |
| 25 | `delete_knowledge` | 删除知识主题 | 协议 |
| 26 | `ocr_image` | 图片理解：MiMo 视觉 → 回退 Tesseract OCR | **真实** |
| 27 | `scrape_page` | 高级爬虫（Scrapling + CSS 选择器，text/html/markdown/links 四模式） | **真实** |
| 28 | `course_advisor` | 智能选课助手（学期 1-8、方向枚举、已修课程） | 协议 |
| 29 | `disaster_control` | 【管理员】灾害预警总控（地震+气象同开） | 协议 |
| 30 | `earthquake_control` | 【管理员】地震预警专用 | 协议 |
| 31 | `weather_control` | 【管理员】气象预警专用 | 协议 |
| 32 | `teacher_advisor` | 教师查询（研究方向/职称/邮箱） | 协议 |
| 33 | `notify_classmate` | 按姓名查通讯录并私聊通知 | **真实** |
| 34 | `notify_all` | 给通讯录每人逐个私聊（≤500 字） | **真实** |
| 35 | `admin_group_control` | 【管理员】群配置管理（11 种 action） | 协议 |
| 36 | `news_control` | 新闻订阅管理 | 协议 |
| 37 | `sing_song` | 唱歌（读 data/songs/songs.json 曲库） | **真实** |
| 38 | `say_voice` | edge-tts 语音（8 音色 + 7 情绪，md5 缓存） | **真实** |

**验证工具注册数**：
```bash
python3 -c "from src.llm.tools import TOOLS; print(len(TOOLS))"              # 38
python3 -c "from src.llm.tools_impl import TOOL_IMPL; print(len(TOOL_IMPL))"  # 38
```

---

## 三、查询类工具详解

> 这些工具由 LLM 意图路由自动调用，用户正常说话即可触发；也可用 CLI 手动验证。

### 10. 知识库问答 🧠

**功能详解**
- 核心检索链：**jieba BM25 关键词**（k1=1.5, b=0.75）→ 逐文件精确匹配 → 三轨模糊搜索（二元组重叠/滑动窗口 SequenceMatcher/标题 boost）→ 自动短词重试（2-4 字候选）。
- 语义搜索（`kb_semantic.py`）：字符 2/3-gram + 英文词 TF-IDF，文档按 500 字符重叠分块，余弦相似度，阈值 0.025；每文档取最高分块。
- 文档导入支持：`.txt/.md` 直读、`.docx`（python-docx → pandoc 回退）、`.pdf`（PyPDF2）、`.xlsx/.xls`（openpyxl 逐 sheet 转文本）。
- `smart_search.py` 集成：7 源聚合加权（见第 14 节）。

**配置方法**
1. 建目录并放入 Markdown 文档：`data/knowledge/`
2. 一键重建三类索引：
```bash
python3 search/rebuild_kb_index.py
```
> 生成 `index.json`（主题索引）、`semantic_index.pkl` + `semantic_cache.npz`（语义）、`bm25_index.pkl`（BM25）。
> ⚠️ 注意：`kb_manage.py` 用绝对路径 `/opt/xiaonai/data/knowledge`，`kb_semantic.py` 用相对路径 `data/knowledge`——若不在 `/opt/xiaonai` 部署，语义索引需先 `cd` 到项目根再跑。

**使用**（对话自动触发 `search_knowledge`；CLI 全套）
```bash
python3 search/kb_manage.py list                          # 列出所有条目
python3 search/kb_manage.py view <主题>                    # 查看条目
python3 search/kb_manage.py add <主题> <内容>              # 新增
python3 search/kb_manage.py add <主题> @<文件路径>          # 从 docx/pdf/txt/xlsx 文件导入
python3 search/kb_manage.py update <主题> <内容>           # 更新
python3 search/kb_manage.py delete <主题>                  # 删除（精确+模糊）
python3 search/kb_manage.py search <关键词>                # BM25→精确→模糊→短词重试
python3 search/kb_manage.py semantic <查询>                # 语义搜索
python3 search/kb_manage.py import <文件路径> [主题]        # 导入文档为条目
python3 search/kb_manage.py reindex                       # 从磁盘重建 index.json
# 兼容入口：
python3 search/kb_search.py <关键词>                       # = kb_manage search
python3 search/kb_search.py -s <查询>                      # = kb_manage semantic
```

**数据存储**：`data/knowledge/*.md`、`index.json`、`bm25_index.pkl`、`semantic_index.pkl`、`semantic_cache.npz`。

---

### 11. 录取分数查询 📊

**功能详解**
- 直连武汉理工招生网官方 API（`zs.whut.edu.cn/enroll-info/recruitByMajor`），120s 内存缓存。
- 自动判断高考制度：2024+ 新高考（物理类/历史类），之前老高考（理工/文史，自动回退映射）。
- 三大输出模式：分数/位次趋势（`--trend`，SAFE/差N分标注）、逐专业分析（`show_score_analysis`，稳妥★/冲刺★↑ + 高频专业三年趋势）、**READY 综合推荐**（风险分层 = 分数差因子 + 招生人数因子，≥5 高/≥3 中/否则低，输出首选/稳妥/冲刺，热门专业优先）。
- `smart_analyze`：QQ 优化输出 🟢保底 / 🟡稳妥 / 🟠冲刺 三档各前 6。

**配置方法**：无（数据来自公开 API）。常量可改：`BASE`（API 地址）、`PROVS`（31 省）。

**使用**
```bash
python3 search/score_query.py list                          # 列出省份
python3 search/score_query.py 湖北                           # 湖北全部年份/科类综合
python3 search/score_query.py 湖北 2024                      # 指定年份
python3 search/score_query.py 湖北 2024 物理类 计算机 --score 620   # 科类+关键词+分数
python3 search/score_query.py 湖北 --score 620               # 620 分能报的专业
python3 search/score_query.py 湖北 --smart                   # 智能招生分析（QQ 优化）
python3 search/score_query.py 湖北 --trend                   # 位次趋势
```

**数据存储**：无（仅内存缓存）。另 `whut_score_api.py` 提供无缓存直连版 + 知识库年份完整性校验：
```bash
python3 campus/whut_score_api.py 湖北 --score 620
python3 campus/whut_score_api.py verify all                 # 校验全部省份知识库覆盖
```

---

### 12. 招生计划查询 📋

**功能详解**（`zs_plan_query.py` + `whut_plan_api.py`）
- 直连 `zs.whut.edu.cn/enroll-info/recruitScheme/` API：分专业招生人数、选科要求、备注；120s 缓存。
- 6 种科类支持；自动遍历全部科类（物理类优先）；按计划类型分组输出 + 合计。

**配置方法**：无。常量：`API_BASE`、`PROVS`、`SUBJECT_TYPES`。

**使用**
```bash
python3 search/zs_plan_query.py 湖北                          # 默认年份 2025，全部科类
python3 search/zs_plan_query.py 湖北 2024 物理类 计算机
python3 campus/whut_plan_api.py 广西 2025 物理类              # 简易版
```

---

### 13. 招生网搜索与校验 🔎

**功能详解**（`zs_whut_search.py`）
- 全站通知公告搜索（最多翻 32 页），正文提取（`<!--主体开始-->` 标记间内容）。
- `verify` 模式：**同时搜招生网和本地知识库，冲突时以知识库为准**。

**使用**
```bash
python3 search/zs_whut_search.py search <关键词>    # 全站标题搜索
python3 search/zs_whut_search.py list [页数]        # 通知列表
python3 search/zs_whut_search.py read <路径>        # 读通知全文
python3 search/zs_whut_search.py verify <关键词>    # 搜索 + 知识库校验
python3 search/zs_whut_search.py scan               # 全站扫描
```

---

### 14. 智能搜索（7 源聚合）🔍

**功能详解**（`smart_search.py` v1.1）
- 同时查 7 个数据源，按可信度加权排序：知识库关键词 BM25（0.95）/ 知识库语义（0.85）/ 录取分数 API（0.90）/ 招生官网（0.85）/ 校园通知（0.80）/ 本地网页搜索代理（0.55）/ 招生计划 API（0.96）。
- 意图自动分类（录取/分数→score_api；招生/计划→enrollment+plan_api；通知/公告→campus；疑问词→web_search；任何查询都含知识库两路）。
- 6 线程并发，总超时 15s；结果带来源标签 + 可信度进度条。

**配置方法**
- **前置依赖**：`searxng_proxy.py` 必须监听 `127.0.0.1:8899`（网页搜索源）；`campus_search.py` 必须可执行。
- ⚠️ **配置陷阱**：仓库根 `search_config.json`（credibility/routing/cache）**当前代码零引用**！可信度实际是 `smart_search.py` L11 硬编码 `CRED` 字典——想调可信度必须改代码。

**使用**
```bash
python3 search/smart_search.py <查询词...>    # 无参数默认查 YOUR_SCHOOL
python3 search/searxng_proxy.py               # 前置：启动网页搜索代理（前台常驻）
curl "http://127.0.0.1:8899/search?q=武汉理工&format=json"   # 验证代理
```

**数据存储**：读 `data/knowledge`；内存缓存（TTL 120s）。

---

### 15. 网页搜索底层（engine / parser / deep_search）

**功能详解**
- `src/search/engine.py`：**百度 + 搜狗 + 必应中国 + DuckDuckGo Lite** 四引擎并行；学术类查询（高考/考研/录取）自动加 `site:edu.cn`；SQLite 缓存 1 小时；20 个词典站垃圾过滤；`search_and_read` 搜索后并发抓页交叉验证。
- `src/search/parser.py`：Scrapling 自适应抓取（失败回退 httpx + 正则），5MB 上限，正文截 4000 字。
- `src/search/deep_search.py`：复杂问题深搜——查询分解（最多 5 个子查询：原句/核心词/段落组合/时间变体/原因变体）→ 并行搜索 → URL 去重 → 相关性评分（3-gram×6 + 域名白/黑名单）→ 抓 Top 页面补充上下文。

**配置方法**：无外部配置；缓存表 `search_cache` 由 `src/memory/db.py` 自动创建。

**使用**：无 CLI（纯库，被工具 `web_search` / `deep_search` / `fetch_url` 调用）。

---

### 16. 学术论文搜索 📄

**功能详解**（`scholar_search.py` v2）
- 直连 **OpenAlex API**（全球 2.44 亿+论文）：标题/作者/年份/DOI/引用数/摘要（从 inverted index 重建）/期刊及类型；作者清洗（剔除机构条目）；rows 上限 50。
- 免费、无需 API Key。被 `docx_export_helper.py` 调用生成论文 .docx。

**使用**
```bash
python3 search/scholar_search.py search 深度强化学习 --rows 5
python3 search/scholar_search.py health          # 健康检查
```

---

### 17. 校园通知搜索 🏫

**功能详解**
- `campus_search.py`：6 大来源（本科生院/学校通知/学院通知/部门资讯/学术讲座/教务处）多线程搜索；CAS 全流程登录（RSA 加密密码）+ WebVPN 编码抓取 + 会话 cookie；结果解码回原始校园 URL。
- `src/whut/client.py`：WebVPN 客户端——CAS 统一认证自动登录（lt/execution + RSA PKCS1v15 加密）+ cookie 双重兜底（`wengine_vpn_ticket`），GBK/UTF-8 自适应解码。
- `campus_fetch.py`：抓取指定校内页面内容。

**配置方法**（`.env`，需要校内账号）
```env
WHUT_USERNAME=学号
WHUT_PASSWORD=密码
WHUT_VPN_TICKET=            # 可选：预置 ticket 免登录
WEBVPN_PROXY=http://127.0.0.1:40000   # 可选代理
```
依赖 `cryptography`（RSA）与 WebVPN 可用性。

**使用**
```bash
python3 campus/campus_search.py <关键词>          # 多线程搜索 6 源
python3 campus/campus_search.py --read <url>      # 读指定页
python3 campus/campus_fetch.py http://i.whut.edu.cn/...
python3 campus/webvpn_rsa_login.py                # 手动刷新登录 ticket（写入 .webvpn_ticket）
```

**数据存储**：`.webvpn_ticket`（根目录，已被 .gitignore）。

---

### 18. 资源搜索 📁

**功能详解**（`resource_search.py`）
- 搜索私有资源站文件**名**（自建网盘类站点），只输出"文件名 + 分享链接（`SITE/?id=xxx`）"，**不暴露 API 下载 URL**。
- Token 自动管理：登录换取 token 缓存到 `.resource_token`（3000s 有效）。
- 20 条课程缩写自动展开：`大物→大学物理`、`计组→计算机组成原理`、`四级→英语 四级 CET4` 等；`--recent` 最近上传、`--dirs` 目录统计。

**配置方法**（`resource_search.py` 头部，**必须替换占位符**）
```python
SITE = "https://你的资源站域名"      # L6
AUTH = {"email": "你的邮箱", "password": "你的密码"}   # L7
```
资源站需提供约定 API：`/api/auth`（登录）、`/api/ai-search`（搜索）、`/api/files?action=recentUploads|listAllDirs`。

**使用**
```bash
python3 search/resource_search.py 高数
python3 search/resource_search.py --recent
python3 search/resource_search.py --dirs
```

**数据存储**：`.resource_token`（token 缓存）。

---

### 19. 新闻 / 天气 📰⛅

**新闻**
- 工具 `get_news`：抓取今日新闻含摘要（调 scheduler 插件抓百度热搜，条数读 `data/news_config.json` 的 `count`，默认 10）。
- 群命令：`/新闻`、`/新闻 科技`（科技/财经分类）。
- 配置：`data/news_config.json`（详见第四章）。

**天气**
- 工具 `get_weather`：QWeather 7 日预报 + 生活指数（紫外线/穿衣/运动/洗车等），**wttr.in 回退**；含穿衣/带伞智能建议（LLM 翻译缓存防重复调用）。
- 群命令：`/天气 北京`、`/天气`（用 DEFAULT_CITY）。
- 配置：`QW_API_KEY` / `QW_API_HOST`（`.env`）。

---

### 20. 课程顾问 / 教师查询 🎓

- `course_advisor`：基于培养方案回答选课问题（学期 1-8、方向枚举：智能网联汽车运用/现代汽车智能服务/未确定、已修课程）。
- `teacher_advisor`：教师研究方向/职称/邮箱查询。
- **配置**：把培养方案、教师信息写入知识库 `data/knowledge/`（如 `车辆工程培养方案.md`、`教师信息.md`），重建索引后自动可用。

---

### 21. 通知同学 / 群发 📨

- `notify_classmate`：按姓名查通讯录（markdown 表格第 2 列姓名）→ 私聊通知；`notify_all`：逐个群发（≤500 字）。
- **配置**：创建通讯录 `data/knowledge/YOUR_CONTACTS_FILE.md`（占位符需替换文件名）：
```markdown
| QQ号 | 姓名 | 角色 |
|------|------|------|
| 123456789 | 张三 | 班长 |
```
- **使用**：对话「通知张三明天开会」；CLI `python3 admin/notify_classmate.py 张三 "消息"`。

---

---

## 四、定时推送详解

> **架构**：`scheduler_v5.py` 是独立常驻守护进程（systemd `xiaonai-scheduler` 托管），每 10 秒轮询，**零 LLM 依赖**（欠费不影响）。NoneBot 插件侧（`src/plugins/scheduler.py`）另有一批 APScheduler 任务。两侧功能不同，见下。

### 22. scheduler_v5.py 总览

**功能详解**
- 推送类型（9 类）：每日天气、新闻晚报、校园通知轮询、地震预警轮询、气象预警轮询、考试倒计时、每日问候、一次性定时消息、每日文件清理。
- **失败预算**：普通任务每天 5 次失败上限（`MAX_DAILY_FAILURES=5`），校园通知宽松到 20 次（约 40 分钟连续失败才停）；达到上限当天跳过该任务。
- **GONE 群容错**：NapCat 返回"移出该群"→ 加入 GONE 列表当日不轰炸，但每周期仍试 1 次，成功自动恢复。
- **发送可靠性**：echo 确认制（5s 超时）+ 失败重连重试（3 次）；WS 断开自动重连（10 次）；启动等 NapCat 最多 60×2s。
- **PID 锁**：`data/scheduler.pid` 防双实例。
- 日志：`logs/scheduler.log`（5MB×5 轮转）。

**启动**
```bash
python3 scheduler_v5.py                    # 前台
# 或 systemd：
sudo systemctl enable --now xiaonai-scheduler
journalctl -u xiaonai-scheduler -f         # 看日志
```

### 23. 订阅配置（scheduler_config.json）

> 首次启动自动生成默认配置；`data/scheduler_config.json`。**推荐用命令管理**（见第五章），也可手改：

```json
{
  "weather":         { "enabled": true, "hour": 7,  "groups": [123456789] },
  "news":            { "enabled": true, "hour": 18, "groups": [123456789] },
  "earthquake":      { "enabled": true, "interval_min": 0.5, "groups": [123456789],
                       "min_magnitude": 4.0,
                       "zones": [
                         { "name": "武汉市区", "lat": 30.59, "lon": 114.30, "radius_km": 50,  "min_mag": 3.0 },
                         { "name": "武汉圈",   "lat": 30.59, "lon": 114.30, "radius_km": 200, "min_mag": 3.0 },
                         { "name": "华中",     "lat": 30.59, "lon": 114.30, "radius_km": 800, "min_mag": 4.0 }
                       ],
                       "exclude_location_kw": ["日本", "印尼"] },
  "weather_warning": { "enabled": true, "interval_min": 10, "groups": [123456789] },
  "campus_daily":    { "enabled": true, "interval_min": 2,  "groups": [123456789] },
  "exam_countdown":  { "enabled": true, "groups": [] },
  "daily_greetings": { "enabled": false, "groups": [],
                       "messages": [ { "time": "08:00", "text": "早上好呀~" } ] },
  "test_group": 123456790
}
```

**各 key 字段说明**

| key | 字段 | 含义 |
|-----|------|------|
| `weather` | enabled / hour / groups | 每日发送时刻（默认 7 点）；目标群 |
| `news` | enabled / hour / groups | 每日时刻（默认 18 点）；目标群 |
| `earthquake` | enabled / interval_min / groups / min_magnitude / **zones** / exclude_location_kw | 轮询间隔（分）；全局最低震级（默认 4.0）；**zones 区域列表（name/lat/lon/radius_km/min_mag，haversine 距离匹配，不配 zones 不推送）**；按位置关键词排除（如"日本"） |
| `weather_warning` | enabled / interval_min / groups | 轮询间隔（默认 10 分钟） |
| `campus_daily` | enabled / interval_min / groups | 轮询间隔（默认 2 分钟） |
| `exam_countdown` | enabled / groups | 每天 ≥7 点推送一次 |
| `daily_greetings` | enabled / groups / messages[].time / messages[].text | 每日问候（默认关） |
| `test_group` | int | 测试群（timed_msg 默认目标等） |

**各推送项行为细节**

| 推送 | 触发 | 依赖配置 | 说明 |
|------|------|---------|------|
| 🌤 每日天气 | 每天 hour 点 | `QW_API_KEY`/`QW_API_HOST` | 7 日预报+生活指数；失败降级 wttr.in；全部群确认送达才记 state |
| 📰 新闻晚报 | 每天 hour 点 | 无 | 百度热搜实时榜前 8 条 |
| 🏫 校园通知 | 每 interval_min | WHUT 账号 | 子进程跑 `campus_daily.py --today`（3 次重试）；空串=当天无新通知静默 |
| 🌍 地震预警 | 每 interval_min | zones 必配 | 只推匹配 zones 的地震；震级标签 M≥7🔴/≥6🟠/≥5🟡；超 6h 跳过；首启预填不推 |
| ⛈ 气象预警 | 每 interval_min | `QW_API_KEY` | QWeather Alert；武汉本地（30.59/114.30）；蓝🔵黄🟡橙🟠红🔴 |
| 📚 考试倒计时 | 每天 ≥7 点 | `exam_countdown.py` 有考试 | 子进程 `push` + `archive`（自动删过期） |
| ☀️ 每日问候 | 每天 messages[].time | — | 只发第一条到点的；groups 空时回退 chat_groups |
| ⏰ 定时消息 | 每轮循环 | timed_msg.json | 到期发送；支持 daily/weekly/monthly 循环 |
| 🧹 文件清理 | 每天 3 点 | — | exports/ 及根目录 tmp_* 超 72h → .trash/（每轮≤20）；.trash 超 7 天物理删除 |

**数据存储**：`scheduler_config.json`、`scheduler_state.json`（失败计数 + 各推送今日已发标记）、`eq_sched_cache.json`（已推地震 ID）、`ww_sched_cache.json`（已推预警 ID）、哨兵 `.eq_sched_init`/`.ww_sched_init`、`scheduler.pid`、`logs/scheduler.log`。

### 24. 考试倒计时管理 📚

**功能详解**（`exam_countdown.py`，SQLite 存储）
- 考试类型自动识别：cet4/cet6/考研/期末/教资/普通话/计算机等（关键词表），不同类型不同鼓励文案（0 天/≤3/≤7/≤14/≤30 分档）。
- `push` 输出 `[exam] PUSH:` 行供 scheduler 解析；自动删除已过期考试。

**使用**
```bash
python3 admin/exam_countdown.py add "英语四级" 2026-06-15 --type cet4 --remind 7
python3 admin/exam_countdown.py add "期末高数" 2026-07-05
python3 admin/exam_countdown.py list
python3 admin/exam_countdown.py days "期末高数"
python3 admin/exam_countdown.py delete "期末高数"
python3 admin/exam_countdown.py push       # 输出待推送 + 清理过期
python3 admin/exam_countdown.py archive    # 只清理过期
```

**数据存储**：`data/exams.db`（表 exams）。

### 25. 一次性定时消息 ⏰

**功能详解**（`timed_msg.py`）
- 群发/私聊；循环模式 `--recurring daily|weekly|monthly` + `--dow`（0=周一..6=周日）/`--dom`；过去时间警告立即发送；已发送超 7 天自动清理。
- 群+私聊同发时自动加 `[CQ:at,qq=user]` 前缀。

**使用**
```bash
python3 admin/timed_msg.py add --group 群号 --at "2026-07-01 19:00" --msg "今晚班会有变"
python3 admin/timed_msg.py add --user QQ号 --at "2026-07-01 19:00" --msg "记得交作业" --recurring weekly --dow 1
python3 admin/timed_msg.py list [--all]
python3 admin/timed_msg.py rm <id>
python3 admin/timed_msg.py pending
python3 admin/timed_msg.py cleanup
```

**数据存储**：`data/timed_msg.json`。

### 26. NoneBot 侧调度插件（src/plugins/scheduler.py）

**功能详解**（与守护进程互补）
- **新闻动态多时段**：`news_config.json` 的 `schedule` 支持最多 4 个时间点（如 `["08:00","12:00","18:00","21:00"]`），每次到点都推；LLM 摘要（与 /新闻 一致）；按时段问候语。
- **闹钟**：对话设置（持久化 alarms.json，启动自动恢复）。
- **日记**：每天 23:59 汇总用户数据生成 `data/diary/YYYY-MM-DD.json`。
- **周报**：每周日 22:00 好感度 delta（只打印不推送）。
- **校园晨报**：每天 07:30 抓 `i.whut.edu.cn/xxtg/gztz_9764.shtml` + 校园网，推给 weather_config.json 的 groups[0]。
- **天气晨推**：每天 06:50 读 `weather_config.json` 推天气。
- **L3 知识合并**：每天 03:30 `merge_cross_user`。
- **订阅命令**：`/新闻订阅`、`/新闻退订`、`/新闻状态`（群/私聊双支持）。

**配置**（`data/news_config.json`）
```json
{ "enabled": true, "schedule": ["18:00"], "count": 10,
  "recipients": [], "groups": [], "custom_message": "", "news_only": true }
```
`data/weather_config.json`：
```json
{ "enabled": true, "city": "武汉", "recipients": [], "groups": [], "custom_message": "" }
```

**数据存储**：`news_config.json`、`news_cache.json`、`alarms.json`、`weather_config.json`、`campus_cache.json`、`data/diary/`。

### 27. 地震预警插件（NoneBot 侧）

**功能详解**（`src/plugins/earthquake.py`，与守护进程版并存）
- 时效优先：只推最近 2 小时内地震；区域分级（武汉 50km M≥3.0 / 200km M≥3.0 / 800km M≥4.0 / 全国境内 M≥4.5）；外国/海域关键词过滤 + 中国地理包围盒兜底。
- 首启哨兵预填 EventID 不推送；消息含震级分级标签（≥7 强烈地震…）。
- ⚠️ 实际轮询间隔 `POLL_INTERVAL=30` 秒（代码注释"2分钟"已过时）。

**配置**（`data/earthquake_config.json`）
```json
{ "enabled": true, "groups": ["群号"] }
```

**使用**（群内）：`/地震订阅`、`/地震退订`、`/地震状态`。

**数据存储**：`earthquake_config.json`、`earthquake_cache.json`、哨兵 `.eq_init_done`。

### 28. 气象预警插件（NoneBot 侧）

**功能详解**（`src/plugins/weather_warning.py`）
- QWeather Alert API，仅推送 headline/senderName 含"武汉"的预警；双时效检查（expireTime 未过 + pubTime 3 小时内）；消息带颜色图标 + 描述 200 字 + 指引 150 字。

**配置**（`data/weather_warning_config.json`）
```json
{ "enabled": true, "groups": [], "interval": 600 }
```
API 凭据：`.env` 的 `QW_API_KEY` / `QW_API_HOST`。

**使用**（群内）：`/气象订阅`、`/气象退订`、`/气象状态`。

---

## 五、群管理与订阅

### 29. 群类型管理 👥

**功能详解**（`admin_group_control.py`）
5 类群，互斥（add 自动从其他列表移除），配置双写（OpenClaw workspace + `data/group_config.json`）并热加载 bridge（POST :8081/reload）：

| 类型 | 行为 | 命令 |
|------|------|------|
| `class_groups` 班级群 | 仅 @ 小奈才回复（静默群） | `add_class_group 群号` |
| `chat_groups` 闲聊群 | 主动回复 | `add_chat_group 群号` |
| `normal_groups` 普通群 | 正常回复（仅 @ 回复、无推送） | `add_normal_group 群号` |
| `mute_groups` 免打扰群 | 全沉默（仅管理员可通知） | `add_mute_group 群号` |
| `blacklist` 黑名单 | 不回复 | `add_blacklist 群号` |

> 未配置的群默认按静默群处理；订阅通知不受群类型影响；机器人被拉入新群自动加 normal_groups。

**使用**
```bash
python3 admin/admin_group_control.py add_class_group 群号
python3 admin/admin_group_control.py remove_class_group 群号
python3 admin/admin_group_control.py add_chat_group 群号
python3 admin/admin_group_control.py add_normal_group 群号
python3 admin/admin_group_control.py add_mute_group 群号
python3 admin/admin_group_control.py add_blacklist 群号
python3 admin/admin_group_control.py set_all_class | set_all_chat | set_all_normal | set_all_mute
python3 admin/admin_group_control.py show_config       # 查看全部配置+订阅
```

**数据存储**（`group_config.json`，5 键）
```json
{
  "class_groups": [123456789],
  "chat_groups": [123456790],
  "normal_groups": [123456791],
  "mute_groups": [],
  "blacklist": []
}
```

### 30. 订阅管理 📡

**使用**（与 scheduler_config.json 联动）
```bash
python3 admin/admin_group_control.py subscribe 群号 all        # 订阅全部推送
python3 admin/admin_group_control.py subscribe 群号 weather
python3 admin/admin_group_control.py subscribe 群号 news
python3 admin/admin_group_control.py subscribe 群号 campus_daily
python3 admin/admin_group_control.py subscribe 群号 earthquake
python3 admin/admin_group_control.py subscribe 群号 weather_warning
python3 admin/admin_group_control.py subscribe 群号 exam_countdown
python3 admin/admin_group_control.py show_config               # 查看订阅明细
```
> ⚠️ **已知 bug**：`unsubscribe` 命令当前不真正执行（`sys.exit(0)` 缩进错误，admin_group_control.py L393-397）。想退订请直接改 `data/scheduler_config.json` 或订阅命令移除群号。

### 31. 主动消息（人格插件）💌

**功能详解**（`src/plugins/personality.py`）
- 5 类主动消息：早安（7:25-35 随机，好感≥35）/ 晚安（22:25-35）/ 想念（>72h 没聊且好感>60 主动私聊）/ 午后分享（15:00，好感≥30）/ 群冒泡（9-20 点随机，只发 chat_groups）。
- 防骚扰控制：被 ignore ≥2 次永久停发、没回复 7 天停、回复后 3 天才再发；单次最多 8 人按好感降序。
- 自动通过好友请求。

**配置**：替换 `ADMIN_QQ_PLACEHOLDER`、`CHAT_GROUP_PLACEHOLDER`；依赖 nonebot_plugin_apscheduler。

**数据存储**：`data/proactive_tracker.json`。

---

## 六、运维管理

### 32. 运维 CLI 🛠

**功能详解**（`admin_cli.py`）：管理 5 个服务（qq / bridge / scheduler / searxng / openclaw），集成健康检查、诊断、自动修复、发消息、会话管理。

**使用**（全部子命令）
```bash
python3 admin/admin_cli.py                                # 无参数 = status
python3 admin/admin_cli.py status                         # 服务状态+健康 JSON+熔断器+磁盘内存
python3 admin/admin_cli.py logs <bridge|qq|openclaw|scheduler|searxng> [n]
python3 admin/admin_cli.py restart <服务名|all>
python3 admin/admin_cli.py agent help|reload|run <消息>|model <id>|clear|sessions
python3 admin/admin_cli.py cron list|rm <id>|run <id>
python3 admin/admin_cli.py timed_msg list|pending|rm <id>|help
python3 admin/admin_cli.py diag                            # 6 段诊断
python3 admin/admin_cli.py fix                             # 自动修复（bridge_health+清锁+重启）
python3 admin/admin_cli.py config show|reload
python3 admin/admin_cli.py send <群号|QQ号> <消息>          # ≥9 位数字=群，否则=QQ
python3 admin/admin_cli.py sessions
```

### 33. 健康自愈 🩺

**功能详解**（`health_check.sh`，362 行，17 项检查）
1. 重启 5 个死掉的服务（restart→verify×8→防崩溃循环）
2. 崩溃节流：45 分钟内重启 ≥4 次 → 暂停自动重启
3. openclaw-gateway HTTP 探测重启（:18789/health）
4. mimo-proxy 探测重启（:8898/health）
5. 陈旧会话锁清理（**PID 校验**，只 kill openclaw/node/agent 进程）
6. 静默/挂死 NapCat 检测（uptime>2h + :3000 无响应 → 重启 qq+bridge）
7. 磁盘压力（≥95% 清理日志+journalctl vacuum；≥90% 告警）
8. 内存压力（<150MB 重启 bridge，仍低重启 NapCat）
9. WARP 内存泄漏守卫（warp-svc RSS>500MB 重启）
10. 日志轮转（>5MB）
11. 运行计数
12. 自检自愈（有故障或 08:00/15:00 槽位 → self_test.py --full → L1/L3 定向修复 → 重测 3×10s）
13. 健康分（100 起扣分制）
14. 运行记录（health_runs.log）
15. admin 私信通知（定时槽 dedup 1440 分钟 / 问题态 dedup 55 分钟）
16. 每日摘要（21:30 一次）
17. 状态 JSON 发布（health_state.json）

**配置**（cron）
```bash
*/15 * * * * /opt/xiaonai/scripts/health_check.sh >> /var/log/health_check.log 2>&1
```
需 ubuntu 用户 NOPASSWD sudo（systemd 服务重启）；flock 防并发。

**数据存储**：`data/health_state.json`、`health_runs.log`、`health_run_counter`、`/var/log/health_check.log`。

### 34. 会话清理 🧹

**功能详解**（`session_cleaner_v2.py`）
- 安全清理 OpenClaw 会话：空闲 <180s 跳过（防删正在使用的会话）、>1800s 强清；**清理前先存摘要**（memory/ + agent/resume_）供续聊；删 PID 已死锁；记忆超 7 天删除。

**使用**
```bash
python3 admin/session_cleaner_v2.py                # 安全清理
python3 admin/session_cleaner_v2.py --force
python3 admin/session_cleaner_v2.py --purge-session <session_key>   # 彻底清除（上下文不可恢复）
```

### 35. 主动巡检 🔍

**功能详解**（`proactive_check.py`，OpenClaw cron 每 10 分钟调用）
- 健康检查（bridge_health.py）+ **闹钟派发**（alarm_manager check → bridge :8081/send 发私聊/群）+ 会话锁统计；有问题私聊告警 admin；否则输出 `All OK`。

**配置**：替换 `ADMIN_QQ_PLACEHOLDER`（L12）；依赖 scheduler_config.json 的 test_group。

### 36. 自检 🔬

**功能详解**（`self_test.py`）
- L1：NapCat OneBot API 探针（:3000/get_login_info）；L3（--full）：openclaw agent ping（全新 session key 防假死，重试 3 次）。

**使用**
```bash
python3 admin/self_test.py            # 仅 L1
python3 admin/self_test.py --full     # L1+L3
```
输出 JSON 到 `data/self_test_state.json`，退出码 0/1。

---

## 七、可选高级功能

### 37. 招生咨询网页 🌐

**功能详解**（`consultation_server.py`，端口 8082）
- 独立 Web 服务：单文件 HTML 聊天 UI（省份/分数/科类快捷输入）→ 会话上下文（自动提取省份/分数/科类）→ 调 OpenClaw Agent（注入 CONSULT.md）+ 集成 smart_search/score_query/kb_manage/whut-search。
- 路由：`GET /`、`POST /api/chat`、`GET /health`；监听 0.0.0.0:8082；会话 1h TTL。

**配置**：可选 `~/.openclaw/agents/main/agent/CONSULT.md`；替换 `YOUR_SCHOOL`；依赖 aiohttp + OpenClaw。

**使用**：`python3 tools/consultation_server.py`，浏览器访问 `http://服务器IP:8082`。

### 38. 文献导出 📄

**功能详解**（`docx_export_helper.py`）
- 搜索论文（委托 scholar_search）→ 生成格式化 .docx：封面（深蓝标题）→ 检索策略表 → 文献清单表（6 列隔行着色）→ 论文详情（DOI 超链接、元数据、摘要 600 字截断）→ 数据来源+免责声明。

**使用**
```bash
python3 tools/docx_export_helper.py search "智能网联汽车" --rows 10 -o exports/报告.docx
python3 tools/docx_export_helper.py from-json <papers.json> -o 报告.docx [--query "检索词"]
```
退出码 0/1/2/3。依赖 python-docx；输出默认 `exports/`。

### 39. 通用文档工具 📁

**功能详解**（`xiaonai_doc_tools_v2.py`）
- 任意文档读取（docx/doc/pdf/pptx/xlsx/md 自动识别）、创建（docx/xlsx/pdf/pptx/md）、格式互转。

**使用**
```bash
python3 tools/xiaonai_doc_tools_v2.py read <文件> [-n N]
python3 tools/xiaonai_doc_tools_v2.py make docx|xlsx|pdf|pptx|md <输出> <标题> <内容...>
python3 tools/xiaonai_doc_tools_v2.py make xlsx <输出> '{"Sheet1":[["a","b"]]}'
python3 tools/xiaonai_doc_tools_v2.py convert <输入> <输出>
```
依赖 python-docx/openpyxl/pdfplumber/python-pptx/reportlab（.doc 需 antiword/catdoc）。

### 40. 消息清洗 🧽

**功能详解**（`strip_md.py` / `strip_md_v2.py`）
- 发送前清洗：去 Markdown、去资源站 URL（保留 `?id=` 分享链）、**脱敏**（邮箱→[邮箱已隐藏]、账号密码/token/api_key→[敏感信息已隐藏]、学号邮箱 `\d{5,12}@whut.edu.cn`）、去 NO_REPLY、去思维链泄漏（英文推理块/元推理句/中文推理块三层裁剪）。

**配置**：替换 `RESOURCE_SITE` 常量。
**使用**：纯库函数（被 bridge 调用）。

---

## 附录 A：占位符完整清单

| 占位符 | 出现位置 | 替换为 |
|--------|---------|--------|
| `ADMIN_QQ_PLACEHOLDER` | bridge.py、mood.py、personality.py、llm/client.py、health_notify.py、proactive_check.py、alarm_manager.py | 班长 QQ |
| `BOT_QQ_PLACEHOLDER` | bridge.py、lucky_draw.py、ai_handler.py | 机器人 QQ |
| `CLASS_GROUP_PLACEHOLDER` | ai_handler.py、scheduler_v5.py（默认配置）、client.py | 班级大群 |
| `CHAT_GROUP_PLACEHOLDER` | personality.py、ai_handler.py、client.py | 闲聊群 |
| `CADRE_GROUP_PLACEHOLDER` | admin_group_control.py、client.py | 班干部群 |
| `TEST_GROUP_PLACEHOLDER` | admin_group_control.py、health_notify.py、timed_msg.py、proactive_check.py | 测试群 |
| `RESOURCE_GROUP_PLACEHOLDER` | ai_handler.py、tools.py | 资料共享群 |
| `YOUR_SCHOOL` / `YOUR_COLLEGE` / `YOUR_MAJOR` / `YOUR_CAMPUS` | client.py、personality.py、consultation_server.py | 学校/学院/专业 |
| `YOUR_CONTACTS_FILE.md` | notify_classmate.py | 通讯录文件名 |
| `RESOURCE_SITE` | strip_md*.py | 资源站域名 |
| `WHUT_ACCOUNT_PLACEHOLDER` / `WHUT_PASSWORD_PLACEHOLDER` | campus_search.py、whut_login.py、webvpn_login.py | 学号/密码 |
| `RESOURCE_EMAIL_PLACEHOLDER` / `RESOURCE_PASSWORD_PLACEHOLDER` | resource_search.py | 资源站账号 |

```bash
# 批量替换示例
grep -rl "ADMIN_QQ_PLACEHOLDER" . | xargs sed -i 's/ADMIN_QQ_PLACEHOLDER/你的QQ号/g'
```

## 附录 B：数据文件一览表（均在 `data/`，已被 .gitignore 隔离）

| 文件/目录 | 内容 | 生成方式 |
|-----------|------|---------|
| `knowledge/*.md` | 知识库文档 | 手动 + `rebuild_kb_index.py` |
| `knowledge/index.json` / `bm25_index.pkl` / `semantic_index.pkl` / `semantic_cache.npz` | 三类检索索引 | `rebuild_kb_index.py` |
| `group_config.json` | 群类型配置 | `admin_group_control.py` |
| `scheduler_config.json` | 推送订阅配置 | `admin_group_control.py subscribe` / 手改 |
| `scheduler_state.json` | 推送状态（今日已发/失败计数） | scheduler 自动 |
| `eq_sched_cache.json` / `ww_sched_cache.json` | 已推地震/预警 ID | scheduler 自动 |
| `timed_msg.json` | 定时消息队列 | `timed_msg.py` |
| `alarms.json` | 闹钟列表 | 对话 / `alarm_manager.py` |
| `exams.db` | 考试倒计时数据库 | `exam_countdown.py` |
| `xiaonai_memory.db` | 记忆 SQLite（L1/L2/L3 层） | 自动 |
| `memory/users/<uid>.json` | 用户记忆 + 8 维好感度 | 自动 |
| `diary/YYYY-MM-DD.json` | 每日聊天日记 | scheduler 插件 23:59 |
| `news_config.json` / `news_cache.json` | 新闻配置/缓存 | 自动 |
| `weather_config.json` | 天气晨推配置 | 自动 |
| `earthquake_config.json` / `earthquake_cache.json` | 地震插件配置/缓存 | `/地震订阅` |
| `weather_warning_config.json` / `weather_warning_cache.json` | 气象插件配置/缓存 | `/气象订阅` |
| `songs/songs.json` | 歌曲曲库 | 手动 |
| `voice_cache/*.mp3` | 语音缓存 | `say_voice` 自动 |
| `proactive_tracker.json` | 主动消息防骚扰记录 | personality 插件 |
| `health_state.json` / `health_runs.log` / `health_run_counter` | 健康自愈状态 | `health_check.sh` |
| `self_test_state.json` | 自检结果 | `self_test.py` |
| `.webvpn_ticket`（根目录） | WebVPN 登录票据 | `webvpn_rsa_login.py` |
| `.resource_token`（根目录） | 资源站令牌 | `resource_search.py` |

## 附录 C：已知问题与陷阱

1. **`search_config.json` 无代码引用**：根目录的智能搜索配置文件是预留的，当前可信度在 `smart_search.py` L11 硬编码。
2. **`unsubscribe` 有 bug**：`admin_group_control.py` 的退订命令不真正执行（L393-397），退订请直接改 `scheduler_config.json`。
3. **`mood.py` L154 占位符**：`record_interaction` 引用 `ADMIN_QQ_PLACEHOLDER`，不替换会 NameError。
4. **知识库路径不一致**：`kb_manage.py` 用绝对路径 `/opt/xiaonai/data/knowledge`，`kb_semantic.py` 用相对 `data/knowledge`——不在 `/opt/xiaonai` 部署时语义索引需在项目根目录运行。
5. **地震轮询间隔**：NoneBot 插件实际 30 秒轮询（代码注释"2分钟"过时）。
6. **占位符是硬前提**：`CLASS_GROUP_PLACEHOLDER` 在 scheduler 默认配置字典里，不替换启动即失败。
7. **好感度是 8 维**（不是 6 维）：早期 6 维旧数据会自动补 50。
8. **OCR 依赖**：MiMo 视觉失败才回落 Tesseract，需要系统装 `tesseract-ocr-chi-sim`。
9. **语音依赖**：`say_voice` 需要 `~/.local/bin/edge-tts`（subprocess 不经过 shell，`~` 由代码 expanduser 展开）。
10. **searxng_proxy 是单线程**：无并发；搜索引擎 HTML 结构变化会导致解析失效（返回空）。

---

> 还找不到答案？对话类功能看 [TOOL-ROUTING.md](TOOL-ROUTING.md)；知识库看 [KNOWLEDGE-BASE-GUIDE.md](KNOWLEDGE-BASE-GUIDE.md)；部署看 [DEPLOYMENT.md](DEPLOYMENT.md)。
